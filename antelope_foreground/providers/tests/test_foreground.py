import unittest
import os
from shutil import rmtree
from uuid import uuid4

from ...entities.fragment_editor import create_fragment
from .. import LcForeground
from antelope import CatalogRef  # , EntityRefMergeError  ## merge error no longer!

WORKING_DIR = os.path.join(os.path.dirname(__file__), 'test-foreground')

test_ref = 'test.foreground'
flow_uuid = str(uuid4())
frag_uuid = str(uuid4())
frag_ext_name = 'the bodacious reference fragment'

a_different_frag_uuid = str(uuid4())
a_different_frag_ref = 'a completely separate reference fragment'

mass_json = {
    'externalId': 'kg',
    'referenceUnit': 'kg',
    'entityType': 'quantity'
}

flow_json = {
    'externalId': flow_uuid,
    'entityType': 'flow',
    'origin': test_ref,
    'CasNumber': '',
    'referenceQuantity': 'kg'
}

frag_json = [{
    'entityId': a_different_frag_uuid,
    'externalId': a_different_frag_ref,
    'entityType': 'fragment',
    'origin': test_ref,
    'flow': flow_uuid,
    'direction': 'Input',
    'parent': None,
    'isPrivate': False,
    'isBackground': False,
    'isBalanceFlow': False,
    'exchangeValues': {
        '0': 1.0,
        '1': 1.0
    },
    'tags': {
        'Comment': 'this is the fragment the test has made'
    },
    'terminations': {
        'default': {}
    }
}]


"""
Foreground unit testing. What does the foreground do?

on top of a basic archive, it:
 - stores, serializes, deserializes fragments
 - allows to name fragments
 - lists fragments
 - requires all entities to either be local or catalog refs
 * some specialty things like finding terminations nd deleting fragments that are not used
 
For now, the only thing we want to test is the renaming of fragments-- after which either uuid or name should retrieve
the fragment.

Then, this will change somewhat when we upgrade fragments to use links instead of uuids, to allow for different 
instances of the same uuid to be stored in the same foreground.
"""


class LcForegroundTestCase(unittest.TestCase):
    """
    Bucking convention to make this a sequential test, because the operations necessarily depend on one another
    """
    @classmethod
    def setUpClass(cls):
        rmtree(WORKING_DIR, ignore_errors=True)
        cls.fg = LcForeground(WORKING_DIR, ref=test_ref)
        cls.fg.entity_from_json(mass_json)
        cls.fg.entity_from_json(flow_json)

    def test_0_retrieve_flow_by_uuid(self):
        myflow = self.fg[flow_uuid]
        self.assertIsNotNone(myflow)

    def test_1_make_fragment(self):
        myflow = self.fg[flow_uuid]
        frag = create_fragment(myflow, 'Output', uuid=frag_uuid, comment='Test Fragment')
        self.fg.add(frag)

    def test_2_retrieve_fragment(self):
        frag = self.fg[frag_uuid]
        self.assertIsNotNone(frag)
        self.assertEqual(frag['Comment'], 'Test Fragment')

    def test_3_name_fragment(self):
        frag = self.fg[frag_uuid]
        self.assertIsNotNone(frag)
        self.fg.name_fragment(frag, frag_ext_name)
        self.assertIs(frag, self.fg[frag_ext_name])

    def test_4_uuid_still_works(self):
        self.assertIs(self.fg[frag_uuid], self.fg[frag_ext_name])

    def test_5_deserialize_named_fragment(self):
        self.fg._do_load(frag_json)
        self.assertEqual(self.fg[a_different_frag_ref].uuid, a_different_frag_uuid)

    def test_6_save_foreground(self):
        self.fg.save()
        new_fg = LcForeground(WORKING_DIR)
        new_fg.make_interface('basic')  # must now trigger fragment load- this happens automatically in query apparatus
        self.assertEqual(self.fg[flow_uuid], new_fg[flow_uuid])
        self.assertEqual(self.fg[a_different_frag_ref].uuid, new_fg[a_different_frag_uuid].uuid)

    def test_7_different_origins(self):
        my_id = uuid4()  # BaseRef SHOULD cast this to str in external_ref assignment, but as of 0.2.1 it doesn't
        f_ref_1 = CatalogRef('fictitious.origin.v1', my_id, entity_type='flow')
        f_ref_2 = CatalogRef('fictitious.origin.v2', my_id, entity_type='flow')
        self.fg.add(f_ref_1)
        '''
        with self.assertRaises(EntityRefMergeError):
            # this will give an error that CatalogRefs can't merge
            self.fg.add(q_ref_2)
        '''
        self.fg.add(f_ref_2)
        self.assertIs(self.fg[f_ref_2.link], f_ref_2)
        self.assertIs(self.fg[f_ref_1.external_ref], f_ref_2)
        self.assertIs(self.fg[f_ref_1.link], f_ref_1)

    @classmethod
    def tearDownClass(cls):
        rmtree(WORKING_DIR)


if __name__ == '__main__':
    unittest.main()
