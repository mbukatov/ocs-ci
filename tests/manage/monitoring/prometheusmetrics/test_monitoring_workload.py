# -*- coding: utf8 -*-
"""
Test cases here requires storage workloads performed via workload fixtures.
"""

import logging

import pytest

from ocs_ci.utility.prometheus import PrometheusAPI


logger = logging.getLogger(__name__)


@pytest.mark.polarion_id("OCS-1303")
def test_monitoring_storageutilization_metrics(
    workload_storageutilization_50p_rbd,
    workload_storageutilization_50p_cephfs
):
    """
    This test case checks that the OCS cluster utilization is reported by OCP
    Prometheus.
    """
    prometheus = PrometheusAPI()

    # TODO: list utilization metrics for queries here:
    # ceph_cluster_total_used_bytes
    # ceph_cluster_total_used_raw_bytes
    # ceph_cluster_total_bytes - is the same
    result_used = prometheus.query_range(
        query='ceph_cluster_total_used_bytes',
        start=workload_storageutilization_50p_rbd['start'],
        end=workload_storageutilization_50p_rbd['stop'],
        step=15)


@pytest.mark.polarion_id("OCS-1304")
def test_monitoring_write_metrics(
    workload_storageutilization_85p_rbd,
    workload_storageutilization_85p_cephfs
):
    prometheus = PrometheusAPI()
