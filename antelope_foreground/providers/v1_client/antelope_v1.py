import json
from collections import defaultdict
from time import time
from antelope import CatalogRef, BasicQuery, comp_dir, NoReference, NoAccessToEntity

from antelope_core.archives import BasicArchive, LC_ENTITY_TYPES
# from lcatools.fragment_flows import FragmentFlow

from ..lc_foreground import FOREGROUND_ENTITY_TYPES
from ...interfaces.iforeground import AntelopeForegroundInterface
from ...refs.fragment_ref import FragmentRef
from ...fragment_flows import FragmentFlow, GhostFragment

from ...terminations import FlowTermination, MissingFlow
from antelope_core.characterizations import DuplicateCharacterizationError
from math import isclose

from .foreground import AntelopeV1ForegroundImplementation
from .quantity import AntelopeQuantityImplementation
from .index import AntelopeIndexImplementation
from .exceptions import AntelopeV1Error

import requests


ANTELOPE_ENTITY_TYPES = LC_ENTITY_TYPES + tuple(filter(lambda k: k not in LC_ENTITY_TYPES, FOREGROUND_ENTITY_TYPES))


try:
    # from urllib.request import urlopen, urljoin
    from urllib.parse import urlparse, urljoin
except ImportError:
    # from urllib2 import urlopen
    from urlparse import urlparse, urljoin


def remote_ref(url):
    p = urlparse(url)
    ref = p.netloc
    for k in p.path.split('/'):
        if len(k) > 0:
            ref = '.'.join([ref, k])
    return ref


class GhostFragmentv1(GhostFragment):
    def __init__(self, parent, top, flow, direction):
        self._top = top
        super(GhostFragmentv1, self).__init__(parent, flow, direction)

    def top(self):
        return self._top


class AntelopeV1Query(BasicQuery, AntelopeForegroundInterface):
    def get_reference(self, external_ref):
        try:
            return super(AntelopeV1Query, self).get_reference(external_ref)
        except NoAccessToEntity:
            raise NoReference(self.origin, external_ref)


class DeferredProcessComment(object):
    def __init__(self, request, process_id):
        super(DeferredProcessComment, self).__init__()
        self._request = request
        self._ppid = process_id
        self._comment = None

    @property
    def comment(self):
        if self._comment is None:
            self._comment = self._request(self._ppid)
        return self._comment

    @property
    def cached(self):
        return self._comment is not None

    def __str__(self):
        return self.comment


class AntelopeV1Client(BasicArchive):
    """
    Provider class for .NET-era Antelope servers.  The basic function is to rely on the interface whenever possible
    but also to cache inventory and LCIA results locally as catalog refs.
    """
    _entity_types = ANTELOPE_ENTITY_TYPES

    def __init__(self, source, ref=None, **kwargs):
        """

        :param source:
        :param catalog:
        :param kwargs:
        """
        if ref is None:
            ref = remote_ref(source)

        self._set_query()

        super(AntelopeV1Client, self).__init__(source, ref=ref, **kwargs)

        self._s = requests.Session()

        # a set of dicts where the key is a string-formatted integer and the value is an entity_ref
        self._endpoints = dict()
        self._cached = defaultdict(dict)

        self._fetched_all = {
            'process': False,
            'flow': False,
            'flowproperty': False,
            'lciamethod': False,
            'fragment': False
        }
        # print('Fetching all flow properties')  ## this makes the difference between a 20 sec test and a 55-sec test
        for fp in self.get_endpoint('flowproperties', cache=False):
            self._parse_and_save_entity(fp)
        # print('done') ## super slow DiscountASP gotta get away
        self._fetched_all['flowproperty'] = True

    def _set_query(self):
        self._query = AntelopeV1Query(self)

    def make_interface(self, iface):
        if iface == 'index':
            return AntelopeIndexImplementation(self)
        elif iface == 'quantity':
            return AntelopeQuantityImplementation(self)
        elif iface == 'foreground':
            return AntelopeV1ForegroundImplementation(self)
        else:
            return super(AntelopeV1Client, self).make_interface(iface)

    def _make_ref(self, external_ref, entity_type, **kwargs):
        if entity_type == 'fragment':
            return FragmentRef(external_ref, self.query, **kwargs)
        r = CatalogRef.from_query(external_ref, self.query, entity_type, **kwargs)
        return r

    def entities_by_type(self, entity_type):
        if entity_type == 'process':
            endp = 'processes'
        elif entity_type == 'flow':
            endp = 'flows'
        elif entity_type == 'flowproperty':
            endp = 'flowproperties'
        elif entity_type == 'lciamethod':
            endp = 'lciamethods'
        elif entity_type == 'fragment':
            endp = 'fragments'
        else:
            raise ValueError('Unknown entity type %s' % entity_type)

        if self._fetched_all[entity_type]:
            for k, v in sorted(self._cached[endp].items()):
                if entity_type == 'flowproperty':
                    if v.is_lcia_method:
                        continue
                elif entity_type == 'lciamethod':
                    if not v.is_lcia_method:
                        continue
                yield v
        else:
            for j in self.get_endpoint(endp, cache=False):
                yield self._parse_and_save_entity(j)
            self._fetched_all[entity_type] = True

    def fragments(self, **kwargs):
        return self.entities_by_type('fragment')

    def get_uuid(self, ext_ref):
        ent = self.retrieve_or_fetch_entity(ext_ref)
        return ent.uuid

    def _load_all(self, **kwargs):
        raise AntelopeV1Error('Cannot load all entities from remote Antelope server')

    def get_endpoint(self, endpoint, cache=True):
        """
        Generally we do not want to cache responses that get parsed_and_saved because that process pop()s
        all the relevant information out of them.
        :param endpoint:
        :param cache:
        :return:
        """
        if endpoint in self._endpoints:
            return self._endpoints[endpoint]

        self._print('Fetching %s from remote server' % endpoint)
        url = urljoin(self.source, endpoint)
        print('loading URL %s' % url)
        t = time()
        j = json.loads(self._s.get(url).content)
        el = time() - t
        print('done [%.2f sec]' % el)

        if cache:
            self._endpoints[endpoint] = j
        return j

    def get_stage_name(self, stage_id):
        stgs = self.get_endpoint('stages')
        stage_id = int(stage_id)
        if stgs[stage_id - 1]['fragmentStageID'] == stage_id:
            return stgs[stage_id - 1]['name']
        try:
            return next(j['name'] for j in stgs if j['fragmentStageID'] == stage_id)
        except StopIteration:
            raise ValueError('Unknown fragment stage ID %d' % stage_id)

    def _ref_to_key(self, key):
        return key

    def _fetch(self, entity, **kwargs):
        j = self.get_endpoint(entity, cache=False)[0]
        return self._parse_and_save_entity(j)

    def _get_comment(self, processId):
        target = '/'.join(['processes', processId, 'comment'])
        j = self.get_endpoint(target)
        return j['comment']

    def _get_impact_category(self, cat_id):
        cats = self.get_endpoint('impactcategories')
        cat_id = int(cat_id)
        try:
            return next(j['name'] for j in cats if j['impactCategoryID'] == cat_id)
        except StopIteration:
            raise ValueError('Unknown impact category ID %d' % cat_id)

    def fetch_flows(self, fragment):
        for f in self.get_endpoint('%s/flows' % fragment, cache=False):
            ext_ref = 'flows/%d' % f['flowID']
            if ext_ref in self._entities:
                continue
            self._parse_and_save_entity(f)

    def make_fragment_flow(self, ff):
        """
            A fragment traversal generates an array of FragmentFlow objects.

    X    "fragmentID": 8, - added by antelope
    X    "fragmentStageID": 80,

    f    "fragmentFlowID": 167,
    f    "name": "UO Local Collection",
    f    "shortName": "Scenario",
    f    "flowID": 371,
    f    "direction": "Output",
    f    "parentFragmentFlowID": 168,
    f    "isBackground": false,

    w    "nodeWeight": 1.0,

    t    "nodeType": "Process",
    t    "processID": 62,

    *    "isConserved": true,
    *    "flowPropertyMagnitudes": [
      {
        "flowPropertyID": 23,
        "unit": "kg",
        "magnitude": 1.0
      }
    ]

        Need to:
         * create a termination
         * create a fragment ref
         * extract node weight
         * extract magnitude
         * extract is_conserved

        :param ff: .from_antelope_v1(ff, self.query)
         JSON-formatted fragmentflow, from a v1 .NET antelope instance.  Must be modified to include StageName
         instead of fragmentStageID
        :return:
        """
        """
        This needs to be in-house because it uses the query mechanism
        :param ff:
        :return:
        """
        fpms = ff['flowPropertyMagnitudes']
        ref_mag = fpms[0]
        magnitude = ref_mag['magnitude']
        flow = self.query.get('flows/%s' % ff['flowID'])
        for fpm in fpms[1:]:
            mag_qty = self.query.get('flowproperties/%s' % fpm['flowPropertyID'])
            if fpm['magnitude'] == 0:
                val = 0
            else:
                val = fpm['magnitude'] / magnitude
            try:
                flow.characterize(mag_qty, value=val)
            except DuplicateCharacterizationError:
                if not isclose(mag_qty.cf(flow), val):
                    raise ValueError('Characterizations do not match: %g vs %g' % (mag_qty.cf(flow), val))

        dirn = ff['direction']

        if 'parentFragmentFlowID' in ff:
            parent_ref = 'fragments/%s/fragmentflows/%s' % (ff['fragmentID'], ff['parentFragmentFlowID'])
            top = self.query.get('fragments/%s' % ff['fragmentID'])
            frag = GhostFragmentv1(parent_ref, top, flow, dirn)  # distinctly not reference

        else:
            frag = self.query.get('fragments/%s' % ff['fragmentID'])

        node_type = ff['nodeType']
        nw = ff['nodeWeight']
        if magnitude == 0:
            inbound_ev = 0
        else:
            inbound_ev = magnitude / nw

        if node_type == 'Process':
            term_node = self.query.get('processes/%s' % ff['processID'])
            term = FlowTermination(frag, term_node, term_flow=flow, inbound_ev=inbound_ev,
                                   _direction=comp_dir(dirn))  # antelope v1 processes do not have reference flows!
        elif node_type == 'Fragment':
            term_node = self.query.get('fragments/%s' % ff['subFragmentID'])
            try:
                term = FlowTermination(frag, term_node, term_flow=flow, inbound_ev=inbound_ev)
            except MissingFlow:
                term = FlowTermination(frag, term_node, term_flow=None, inbound_ev=inbound_ev)
        else:
            term = FlowTermination.null(frag)
        if 'isConserved' in ff:
            conserved = ff['isConserved']
        else:
            conserved = False

        return FragmentFlow(frag, magnitude, nw, term, conserved)

    '''
    Entity handling
    '''
    def retrieve_or_fetch_entity(self, key, **kwargs):
        """
        A key in v1 antelopev1 is 'datatype/index' where index is a sequential number starting from 1.  The archive also
        caches references locally by their uuid, so retrieving an entity by uuid will work if the client has already
        come across it.
        :param key:
        :param kwargs:
        :return:
        """
        ent = None

        if key in self._entities:
            return self._entities[key]

        parts = key.split('/')
        if len(parts) != 2:
            raise KeyError('%s: Key must be of the format "entity_type/id"' % key)
        if parts[1] in self._cached[parts[0]]:
            ent = self._cached[parts[0]][parts[1]]
        if ent is not None:
            return ent
        else:
            return self._fetch(key, **kwargs)

    def _parse_and_save_entity(self, j):
        """
        Take a json object obtained from a query and use it to create an entity ref
        :param j:
        :return:
        """
        func = {'process': self._parse_and_save_process,
                'flow': self._parse_and_save_flow,
                'lciamethod': self._parse_and_save_lcia,
                'flowproperty': self._parse_and_save_fp,
                'fragment': self._parse_and_save_fragment}[j.pop('resourceType').lower()]
        j.pop('links')
        obj = func(j)
        self.add_entity_and_children(obj)
        return obj

    def _parse_and_save_process(self, j):
        process_id = str(j.pop('processID'))
        ext_ref = 'processes/%s' % process_id
        j['Name'] = j.pop('name')
        j['SpatialScope'] = j.pop('geography')
        j['TemporalScope'] = j.pop('referenceYear')
        j['Comment'] = DeferredProcessComment(self._get_comment, process_id)
        ref = self._make_ref(ext_ref, 'process', reference_entity=[], **j)
        self._cached['processes'][process_id] = ref
        return ref

    def _parse_and_save_flow(self, j):
        flow_id = str(j.pop('flowID'))
        ext_ref = 'flows/%s' % flow_id
        j['Name'] = j.pop('name')
        j['CasNumber'] = j.pop('casNumber', '')
        j['Compartment'] = [j.pop('category')]
        ref_qty = self.retrieve_or_fetch_entity('flowproperties/%s' % j.pop('referenceFlowPropertyID'))
        ref = self._make_ref(ext_ref, 'flow', reference_entity=ref_qty, **j)
        self._cached['flows'][flow_id] = ref
        return ref

    def _parse_and_save_lcia(self, j):
        lm_id = str(j.pop('lciaMethodID'))
        ext_ref = 'lciamethods/%s' % lm_id
        j['Name'] = j.pop('name')
        j['Method'] = j.pop('methodology')
        rfp = j.pop('referenceFlowProperty')
        ref_unit = rfp['referenceUnit']
        j.pop('referenceFlowPropertyID')
        j['Indicator'] = rfp['name']
        j['Category'] = self._get_impact_category(j.pop('impactCategoryID'))
        ref = self._make_ref(ext_ref, 'quantity', reference_entity=ref_unit, **j)
        self._cached['lciamethods'][lm_id] = ref
        return ref

    def _parse_and_save_fp(self, j):
        fp_id = str(j.pop('flowPropertyID'))
        ext_ref = 'flowproperties/%s' % fp_id
        j['Name'] = j.pop('name')
        ref_unit = j.pop('referenceUnit')
        ref = self._make_ref(ext_ref, 'quantity', reference_entity=ref_unit, **j)
        self._cached['flowproperties'][fp_id] = ref
        return ref

    def _parse_and_save_fragment(self, j):
        frag_id = str(j.pop('fragmentID'))
        ext_ref = 'fragments/%s' % frag_id
        j['Name'] = j.pop('name')
        dirn = j.pop('direction')
        flow = self.retrieve_or_fetch_entity('flows/%s' % j.pop('termFlowID'))
        ref = self._make_ref(ext_ref, 'fragment', flow=flow, direction=dirn, **j)
        self._cached['fragments'][frag_id] = ref
        return ref
