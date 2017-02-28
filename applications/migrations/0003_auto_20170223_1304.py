# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-02-23 05:04
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_address_emailuserprofile_organisation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('applications', '0002_auto_20170223_0958'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='applicant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='application',
            name='organisation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='accounts.Organisation'),
        ),
        migrations.AlterField(
            model_name='document',
            name='category',
            field=models.IntegerField(blank=True, choices=[(1, 'Landowner consent'), (2, 'Deed'), (3, 'Assessment report'), (4, 'Referee response'), (5, 'Lodgement document')], null=True),
        ),
    ]