# -*- coding: utf8 -*-
import logging

import pytest

from ocs_ci.utility.prometheus import PrometheusAPI
# from ocs_ci.ocs.ocp import OCP
# from tests import helpers


logger = logging.getLogger(__name__)


@pytest.mark.libtest
def test_fio_workload(workload_fio_rw_cephfs):
    prometheus = PrometheusAPI()
    logger.info(workload_fio_rw_cephfs)
