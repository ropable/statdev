# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-03-10 02:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0014_referral_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='PublicationFeedback',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effective_to', models.DateTimeField(blank=True, null=True)),
                ('name', models.CharField(max_length=256)),
                ('address', models.CharField(max_length=256)),
                ('suburb', models.CharField(max_length=100)),
                ('state', models.IntegerField(choices=[(1, 'Western Australia'), (2, 'New South Wales'), (3, 'Victoria'), (4, 'South Australia'), (5, 'Northern Territory'), (6, 'Queensland'), (7, 'Australian Capital Territory'), (8, 'Tasmania')])),
                ('postcode', models.CharField(max_length=4)),
                ('phone', models.CharField(max_length=20)),
                ('email', models.EmailField(max_length=254)),
                ('comments', models.TextField(blank=True, null=True)),
                ('documents', models.FileField(upload_to=b'')),
                ('status', models.CharField(max_length=20)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='applications.Application')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='PublicationNewspaper',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effective_to', models.DateTimeField(blank=True, null=True)),
                ('date', models.DateField(blank=True, null=True)),
                ('newspaper', models.CharField(max_length=150)),
                ('documents', models.FileField(upload_to=b'')),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='applications.Application')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='PublicationWebsite',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effective_to', models.DateTimeField(blank=True, null=True)),
                ('original_document', models.FileField(upload_to=b'')),
                ('published_document', models.FileField(upload_to=b'')),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='applications.Application')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]