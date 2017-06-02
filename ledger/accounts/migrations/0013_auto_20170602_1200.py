# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-06-02 04:00
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_auto_20170530_1650'),
    ]

    operations = [
        migrations.AlterField(
            model_name='address',
            name='oscar_address',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='profile_addresses', to='address.UserAddress'),
        ),
        migrations.AlterField(
            model_name='address',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='profile_adresses', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name='address',
            unique_together=set([]),
        ),
    ]