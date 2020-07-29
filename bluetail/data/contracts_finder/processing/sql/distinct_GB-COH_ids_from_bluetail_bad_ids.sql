-- Distinct CH IDs to lookup in OpenOwnership data
select distinct
    party_identifier_scheme,
    party_identifier_id
from
    public.bluetail_ocds_tenderers_view
where
    party_identifier_scheme = 'GB-COH'
    and length(party_identifier_id) != 8
order by party_identifier_id
;