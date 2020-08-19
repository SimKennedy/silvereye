# Generated by Django 2.2.14 on 2020-08-19 11:02

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('input', '0008_supplieddata_data_schema_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='Publisher',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('publisher_id', models.CharField(max_length=1024, null=True)),
                ('publisher_name', models.CharField(max_length=1024, null=True)),
                ('contact_name', models.CharField(blank=True, default='', max_length=1024, null=True)),
                ('contact_email', models.CharField(blank=True, default='', max_length=1024, null=True)),
                ('contact_telephone', models.CharField(blank=True, default='', max_length=1024, null=True)),
            ],
            options={
                'db_table': 'silvereye_publisher_metadata',
            },
        ),
        migrations.CreateModel(
            name='PublisherMetrics',
            fields=[
                ('publisher_id', models.CharField(max_length=1024, primary_key=True, serialize=False)),
                ('publisher_name', models.CharField(max_length=1024)),
                ('count_lastmonth', models.IntegerField(null=True)),
                ('count_last3months', models.IntegerField(null=True)),
                ('count_last12months', models.IntegerField(null=True)),
                ('average_lastmonth', models.IntegerField(null=True)),
                ('average_last3months', models.IntegerField(null=True)),
                ('average_last12months', models.IntegerField(null=True)),
            ],
            options={
                'db_table': 'silvereye_publisher_metrics',
            },
        ),
        migrations.CreateModel(
            name='FileSubmission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('publisher', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='silvereye.Publisher')),
                ('supplied_data', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='input.SuppliedData')),
            ],
        ),
    ]
