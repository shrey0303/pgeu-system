# -*- coding: utf-8 -*-
# Generated by Django 1.11.18 on 2019-09-06 22:27
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0015_pendingbanktransaction_longer_sender'),
        ('transferwise', '0004_transferwise_payout_completeness'),
    ]

    operations = [
        migrations.CreateModel(
            name='TransferwiseMonthlyStatement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField()),
                ('downloaded', models.DateTimeField(auto_now_add=True)),
                ('contents', models.BinaryField()),
                ('paymentmethod', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='invoices.InvoicePaymentMethod')),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='transferwisemonthlystatement',
            unique_together=set([('month', 'paymentmethod')]),
        ),
    ]
