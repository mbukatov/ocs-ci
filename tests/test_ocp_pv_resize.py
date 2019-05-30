# -*- coding: utf8 -*-

"""
This is **work in progress**. Not expected to be merged in a near future.

The code uses plain python and pytest features to keep this as simple as
possible, while allowing to get 1st version quickly.  When the structure of
ocs-ci settles down a bit, all pytest fixtures will be placed into appropriate
conftest.py file, yaml templates and functionality from ocs qe module(s) will
be used and so on.

The primary concern is testcase OCS-304, but cases OCS-300 -- OCS-305 are
similar and could be placed into this file later.

Other purpose of this initial desing of this test is to demonstrate some core
pytest features. There are more comments than necessary.

References:

* Test cases OCS-304, see also: OCS-300 -- OCS-305
* Storage Classess: https://kubernetes.io/docs/concepts/storage/storage-classes/
* Persistent Volumes: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
* Expansion of PV: https://docs.openshift.com/container-platform/4.1/storage/expanding-persistent-volumes.html
"""


import logging
import subprocess
import textwrap
import time

import jinja2
import pytest
import yaml

from ocs.ocp import OCP
from ocsci import tier1


logger = logging.getLogger(__name__)


# TODO: this is a good candicate for general fixture usable in all tests
# TODO: we could read params values from config file if necessary
@pytest.fixture(params=["default", "ocsqe"])
def namespace(request):
    """
    Unique k8s namespace for a test case.
    """
    if request.param == "default":
        ns_name = request.param
    else:
        # note: I can't use create_unique_resource_name() helper here,
        # because namespace must match '[a-z0-9]([-a-z0-9]*[a-z0-9])?'
        # TODO: BUG create_unique_resource_name has one argument, uses dashes
        timestamp = int(time.time() * 1000)
        ns_name = f"{request.param}-{timestamp}"
    if request.param != "default":
        # TODO: use some qe "oc wrapper" function instead of subprocess.run
        # raises an exception for nonzero retcode
        subprocess.run(["oc", "create", "namespace", ns_name], check=True)
    yield ns_name
    if request.param != "default":
        subprocess.run(["oc", "delete", "namespace", ns_name], check=True)


# TODO: parametrize for 2 storage backends: Ceph RBD and CephFS
# @pytest.fixture(params=["rbd", "cephfs"])
@pytest.fixture
def storageclass_expand(tmpdir):
    """
    StorageClass with ``allowVolumeExpansion`` set to ``true``.

    Note that StorageClass is cluster wide resource and as such doen't have
    namespace itself (in the same way as PV doesn't have namespace).

    Right now, it's based on Ceph RBD (rook ceph block), but the test which
    will use it doen't care about such details.
    """
    # name of storageclass is based on rook-ceph-block storage class
    sc_name = "rook-ceph-block-expand"

    # The storage class itself is based on default one (created during
    # ocs-ci deployment) in storage-manifest.yaml
    # TODO: BUG I can't use generate_yaml_from_jinja2_template_with_data
    #       because it fails on
    #       yaml.composer.ComposerError: expected a single document in the stream
    # TODO: coordinate some changes to make such reuse more reasonable
    # TODO: consider creating new template for this particular purpose (but
    #       then there is a sync issue)

    # load default storage class from storage-manifest.yaml into sc_doc
    sc_doc = None
    with open("templates/ocs-deployment/storage-manifest.yaml", "r") as fo:
        template = jinja2.Template(fo.read())
        manifest = template.render()
        for doc in  yaml.load_all(manifest):
            if doc['kind'] == 'StorageClass' and doc['metadata']['name'] == 'rook-ceph-block':
                sc_doc = doc
    assert sc_doc is not None, "there is StorageClass rook-ceph-block in storage-manifest.yaml"

    # minimal changes of the default sc to make it expandable
    sc_doc['metadata']['name'] = sc_name
    sc_doc['allowVolumeExpansion'] = True

    # TODO: test what these options will do:
    # - reclaimPolicy: Delete
    # - volumeBindingMode: Immediate

    # TODO: useful function would be something like:
    #       oc create which takes tmpdir and yaml dict as an input

    # save the storageclass into temporary yaml file
    sc_file = tmpdir.join(f"{sc_name}.yaml")
    sc_file.write(yaml.dump(sc_doc))

    # and finally, create the k8c object
    ocp_sc = OCP(kind='storageclass')
    sc_data = ocp_sc.create(yaml_file=sc_file)
    assert sc_data['metadata']['creationTimestamp']

    # pass whole kubernetes dict for the storageclass to the test case
    yield sc_data

    # teardown
    ocp_sc.delete(yaml_file=sc_file)


@tier1
@pytest.mark.ocs304
@pytest.mark.rhbz1713579
def test_ocs304_pv_delete_after_resize(namespace, storageclass_expand, tmpdir):
    # create pvc
    ocp_pvc = OCP(kind='storageclass')
