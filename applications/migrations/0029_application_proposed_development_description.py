# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-30 05:56
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0028_auto_20170329_1445'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='proposed_development_description',
            field=models.TextField(blank=True, null=True),
        ),
    ]