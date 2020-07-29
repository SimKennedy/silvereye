"""
Gets awards from contracts finder source data with condition on one supplier matching in companies house
Upgrading them to 1.1 OCDS
Altering them to Tender type
Skipping rows with less than 2 supplier that can be matched to BODS
"""
import json
from datetime import datetime, timedelta
from collections import OrderedDict
from urllib.parse import urlparse
from django.conf import settings
import psycopg2
import logging
import random
import os

from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search

from ocdskit.upgrade import upgrade_10_11


ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL")
DATABASE_URL = os.environ.get('DATABASE_URL')
OPENOPPS_DB_URL = os.environ.get('OPENOPPS_DB_URL')
OCDS_OUTPUT_DIR = os.path.join(settings.BLUETAIL_APP_DIR, "data", "contracts_finder", "processing")


def get_company_statements(
        company_id,
        scheme='GB-COH',
        elastic_conn=Elasticsearch(ELASTICSEARCH_URL, verify_certs=True),
):
    s = Search(using=elastic_conn, index="bods") \
        .filter("term", identifiers__scheme__keyword=scheme) \
        .filter("term", identifiers__id__keyword=company_id)

    res = s.execute()
    statements = [s["_source"] for s in res.hits.hits]
    return statements


def connect_from_url(url):
    result = urlparse(url)
    # TODO add common exceptions
    connection = psycopg2.connect(user=result.username,
                                  password=result.password,
                                  host=result.hostname,
                                  port=result.port,
                                  database=result.path[1:])
    return connection


def fix_cf_supplier_ids(json):
    """Modify Contracts Finder OCDS JSON enough to be processed
    """
    try:
        json['version'] = '1.0'
        for i, supplier in enumerate(json['releases'][0]['awards'][0]['suppliers']):
            json['releases'][0]['awards'][0]['suppliers'][i]['id'] = str(i)
    except:
        logging.info('Failed to add supplier IDs', exc_info=True)
    return json


def get_json_from_db(conn):
    """
    Get contracts finder award notices where at least one supplier matches in CH
    """
    query = """
            SELECT DISTINCT t.json AS ocds_json,
                            t.json -> 'releases' -> 0 ->> 'ocid' AS ocid,
                            t.source_id AS source_id
            FROM
             pipeline.cf_notices_ocds t,
            LATERAL jsonb_array_elements(t.json -> 'releases' :: TEXT -> 0 -> 'awards' :: TEXT) award(value),
            LATERAL jsonb_array_elements(award -> 'suppliers') WITH ORDINALITY AS a(supplier, aw_supplier_array_id)
            INNER JOIN ocds.orgs_lookup_distinct orgs_supplier ON (orgs_supplier.org_string = upper(supplier ->> 'name'))
            WHERE TRUE
                AND orgs_supplier.scheme='GB-COH'
                AND length(orgs_supplier.id) = 8
                AND jsonb_array_length(award -> 'suppliers') > 2
                AND award <> 'null'
                AND date_created>'2020-01-01'
                AND date_created<'2020-06-01'
            ;
    """
    cursor = conn.cursor()
    cursor.execute(query)
    record = cursor.fetchall()
    return record


def insert_1_1_json(json, source_id, ocid, conn):
    try:
        query = """
                INSERT INTO scrap.cf_ocds_1_1 (ocds_json, source_id, ocid)
                VALUES (%s, %s, %s)
        """
        vals = (json, source_id, ocid)
        cursor = conn.cursor()
        cursor.execute(query, vals)
        conn.commit()

    except:
        logging.info('Failed to insert 1.1 OCDS', exc_info=True)


def get_and_insert_1_1_json(row):
    try:
        # Fixing json format
        rowjson = json.dumps(row[0])
        rowjson = json.loads(rowjson)

        # Fixing OCDS errors
        rowjson = fix_cf_supplier_ids(rowjson)

        json_1_1 = upgrade_10_11(json.loads(json.dumps(rowjson), object_pairs_hook=OrderedDict))
        json_1_1 = json.dumps(json_1_1)

        insert_1_1_json(json_1_1, row[1], row[2], local_connection)
    except:
        logging.debug('Failed to get 1.1 OCDS', exc_info=True)


def get_1_1_ocds(conn, schema, table, limit=None):
    """ Get converted 1.1 OCDS notices
     """
    query = """
    SELECT ocds_json, ocid
    FROM %s.%s
    ORDER BY ocid
    """ % (schema, table)
    if limit:
        query += ' LIMIT %s' % limit
    cursor = conn.cursor()
    cursor.execute(query)
    record = cursor.fetchall()
    return record


def match_supplier_info(conn, supplier):
    query = """
            SELECT id, scheme, legal_name
            FROM ocds.orgs_lookup_distinct
            WHERE org_string = upper('%s')
            ;
    """ % supplier
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchall()


def update_parties(ocdsjson, dataset='BODS'):
    """ Change suppliers to tenderers """

    parties = ocdsjson['releases'][0]['parties']
    newparties = []
    tenderers = []

    for i, party in enumerate(parties):
        if 'supplier' in party['roles']:

            supplier = party['name']
            sup_info = match_supplier_info(oo_connection, supplier)

            if dataset in ('BODS', 'suppliers'):
                # Skips adding supplier if a match isn't found in Companies House
                if not sup_info:
                    continue

            if dataset == 'BODS':
                # Skips adding supplier if not found in BODS elastic index
                bodsmatch = get_company_statements(sup_info[0][0])
                if not bodsmatch:
                    continue

            try:
                # Adding supplier info from Companies house
                party['identifier'] = {"id": sup_info[0][0],
                                       "scheme": sup_info[0][1],
                                       "legalName": sup_info[0][2]}
            except:
                logging.info('No CH match')

            party['roles'].append('tenderer')
            party['id'] = str(i)

            tenderers.append({
                'id': str(i),
                'name': supplier
            })
            newparties.append(party)
        else:
            newparties.append(party)

    ocdsjson['releases'][0]['parties'] = newparties
    # print('Sucessfully matched tenders:', len(tenderers))
    ocdsjson['releases'][0]['tender']['numberOfTenderers'] = len(tenderers)
    ocdsjson['releases'][0]['tender']['tenderers'] = tenderers
    ocdsjson['releases'][0]['awards'][0]['suppliers'] = tenderers
    return ocdsjson


def fix_dates(d_json, aws):
    tenderenddate = d_json['releases'][0]['tender']['tenderPeriod']['endDate']
    weeksback = random.randint(1, 12)
    newpubdate = (datetime.strptime(tenderenddate, '%Y-%m-%dT%H:%M:%SZ') - timedelta(weeks=weeksback)).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    newpubdate_str = str(newpubdate)
    d_json['releases'][0]['date'] = newpubdate_str

    # Move contract period to tender section
    if aws["contractPeriod"]:
        d_json['releases'][0]['tender']["contractPeriod"] = aws["contractPeriod"]
    try:
        for item in d_json['releases'][0]['tender']['milestones']:
            if item['title'] == 'Contract start':
                d_json['releases'][0]['tender']["contractPeriod"] = {}
                d_json['releases'][0]['tender']["contractPeriod"]['startDate'] = item['dueDate']
            if item['title'] == 'Contract end':
                d_json['releases'][0]['tender']["contractPeriod"]['endDate'] = item['dueDate']
        del d_json['releases'][0]['tender']['milestones']
    except:
        logging.debug('No contract dates found', exc_info=True)

    return d_json


def aws_to_tender(json_ocds, dataset='BODS'):
    """ Converts a Contracts Finder award to tender """

    awards = json_ocds['releases'][0]['awards']
    if len(awards) > 1:
        logging.warning('Notice contains multiple awards which are not currently processed')
    award_info = awards[0]
    json_ocds['releases'][0]['tag'][0] = 'tender'

    json_ocds = update_parties(json_ocds, dataset=dataset)
    json_ocds = fix_dates(json_ocds, award_info)
    return json_ocds


def del_nulls(d):
    for key, value in list(d.items()):
        if not value:
            if key != 'id':
                del d[key]
        elif isinstance(value, dict):
            del_nulls(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    del_nulls(item)
    return d


def insert_clean_1_1_tenders_postgres(ocds_tender, conn):
    ocid = ocds_tender['releases'][0]['ocid']
    try:
        # """
        #     CREATE table scrap.cf_augmented_tenders(
        #         ocid TEXT UNIQUE NOT NULL,
        #         json jsonb
        #     )
        #     ;"""
        query = """
                    INSERT INTO scrap.cf_augmented_tenders (json, ocid)
                    VALUES (%s, %s)
                    ON CONFLICT ("ocid")
                    DO UPDATE SET (json, ocid) = ROW(%s, %s)

            """
        vals = (json.dumps(ocds_tender), ocid)
        cursor = conn.cursor()
        cursor.execute(query, vals)
        conn.commit()
    except:
        logging.info('Failed to insert 1.1 OCDS', exc_info=True)


def insert_clean_1_1_tenders(ocds_tender, conn, dataset):

    ocid = tenders_json['releases'][0]['ocid']
    dataset_dir = 'json_1_1_bods_match'
    if dataset == 'BODS':
        tenders_json['releases'][0]['ocid'] = ocid.replace('-b5fd17-', '-b5fd17bodsmatch-')
        dataset_dir = 'json_1_1_bods_match'
    elif dataset == 'suppliers':
        tenders_json['releases'][0]['ocid'] = ocid.replace('-b5fd17-', '-b5fd17suppliermatch-')
        dataset_dir = 'json_1_1_supplier_ids_match'
    elif dataset == 'raw':
        tenders_json['releases'][0]['ocid'] = ocid.replace('-b5fd17-', '-b5fd17raw-')
        dataset_dir = 'json_1_1_raw'

    ocid = tenders_json['releases'][0]['ocid']
    filedir = os.path.join(OCDS_OUTPUT_DIR, dataset_dir, '%s.json' % ocid)
    with open(filedir, 'w') as dataloc:
        dataloc.write(json.dumps(tenders_json))

    insert_clean_1_1_tenders_postgres(ocds_tender, conn)


if __name__ == '__main__':

    local_connection = connect_from_url(DATABASE_URL)
    oo_connection = connect_from_url(OPENOPPS_DB_URL)

    # set dataset to
    # BODS: all suppliers have a match in the BODS dataset, other natural suppliers are removed
    # suppliers: Suppliers have a match with a Companies House ID in the OpenOpps orgs table, other suppliers are removed
    # raw: All suppliers are included, and CH IDs are added where a match is found
    dataset = 'BODS'

    # Get the Contracts Finder notices as they are and convert to OCDS 1.1
    response = get_json_from_db(oo_connection)
    for row in response:
        get_and_insert_1_1_json(row)

    response = get_1_1_ocds(local_connection, 'scrap', 'cf_ocds_1_1', limit=500)
    i = 0
    for row in response:

        tenders_json = aws_to_tender(row[0], dataset=dataset)
        if tenders_json['releases'][0]['tender']['numberOfTenderers'] < 2:
            continue

        # Remove null json fields from OCDS
        # clean_ocds_json = del_nulls(tenders_json)

        print(json.dumps(tenders_json))
        insert_clean_1_1_tenders(tenders_json, local_connection, dataset)

        i += 1
        if i == 100:
            break

    oo_connection.close()
    local_connection.close()
