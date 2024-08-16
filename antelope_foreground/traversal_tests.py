"""
LCA Test

We need an efficient way to test a model under code changes and evolution to identify when results change.
This architecture was inspired by a set of ad hoc tests I wrote for CATRA-yoy.  The idea is to generate a
concise serializable record of an LCA computation and store it, and then later on to deserialize and compare to live
results.

The serializable record is a set of tuples ('contextual name', 'contextual_value'). For testing purposes, a string
equality combined with a stable rounding method was judged to provide the best confidence.  "rounding" method applies
the format '%.*g' % (self.precision, contextual_value).  precision defaults to 8.

"""

from pydantic import BaseModel, field_serializer, ConfigDict
from typing import Set, Tuple, List
from antelope import QuantityRef, EntityNotFound, CatalogRef
from antelope_core.entities import LcQuantity
from antelope.models import EntityRef

from collections import defaultdict
import json
import os


def _num(entry):
    name, value = entry
    try:
        return float(value)
    except TypeError:
        print('glitch on value %s' % value)
        return 0.0


class _FragmentLcaTest(BaseModel):
    test: str
    """
    A set of results for a given resource.  Subclasses will specify HOW to generate + compare the results
    """
    origin: str
    external_ref: str
    precision: int
    scenarios: List[str] = []
    results: Set[Tuple[str, str]] = {}

    @property
    def name(self):
        return 'Test %s: %s/%s (%s)' % (self.test, self.origin, self.external_ref, self.scenarios)

    @classmethod
    def from_model(cls, model, *scenarios, precision=None, **kwargs):
        if precision is None:
            precision = 8
        cot = cls(origin=model.origin, external_ref=model.external_ref, precision=precision, scenarios=scenarios,
                  **kwargs)
        cot.set(model)
        return cot

    def rounding(self, value):
        return '%.*g' % (self.precision, value)

    def run(self, model) -> Set[Tuple[str, str]]:
        return NotImplemented

    def set(self, model):
        self.results = self.run(model)

    def check(self, model):
        test = self.run(model)
        first = test.difference(self.results)
        second = self.results.difference(test)
        if len(first) == 0 and len(second) == 0:
            return True
        else:
            print('In Test:')
            if first:
                for i in sorted(first, key=_num, reverse=True):
                    print(i)
            else:
                print('all accounted')
            print('\nIn Results:')
            if second:
                for i in sorted(second, key=_num, reverse=True):
                    print(i)
            else:
                print('all accounted')
            return False


class CutoffsTest(_FragmentLcaTest):
    test: str = 'cutoff'

    def run(self, model):
        cos = model.cutoffs(scenario=self.scenarios)
        return set((k.flow.external_ref, self.rounding(k.value)) for k in cos)


class ActivityTest(_FragmentLcaTest):
    """
    Note: this does not work for dynamically generated models because UUIDs won't match- use FragmentFlowsTest instead
    """
    test: str = 'activity'

    def run(self, model):
        act = model.activity(scenario=self.scenarios)
        return set((obj.fragment.external_ref, self.rounding(obj.node_weight)) for obj in act)


class FragmentFlowsTest(_FragmentLcaTest):
    """
    really this result set should be a list, but it will still run deterministically because it will
    store all encountered combinations of each flow + magnitude

    """
    test: str = 'flows'

    def run(self, model):
        ffs = model.traverse(scenario=self.scenarios)
        return set((ff.fragment.flow.name, self.rounding(ff.magnitude)) for ff in ffs)


class _LciaTest(_FragmentLcaTest):
    """
    This is sloppy because we need live quantities to run the tests
    we wouldn't need to do this if we had a query
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    lcia_method: QuantityRef | LcQuantity  # we keep a live query on hand

    @property
    def name(self):
        return 'Test %s: %s/%s (%s) | %s' % (self.test, self.origin, self.external_ref, self.scenarios,
                                             self.lcia_method.name)

    def check(self, model):
        if not self.lcia_method.is_entity:
            if not self.lcia_method.resolved:
                return False
        return super(_LciaTest, self).check(model)

    @field_serializer('lcia_method')
    def serialize_field(v):
        """
        we serialize as an EntityRef so that we can retrieve it at runtime
        :return:
        """
        return EntityRef.from_entity(v)


class LciaTotalTest(_LciaTest):
    test: str = 'lcia_total'

    def run(self, model):
        res = model.fragment_lcia(self.lcia_method, scenario=self.scenarios)
        return {(self.external_ref, self.rounding(res.total()))}


class LciaContribTest(_LciaTest):
    test: str = 'lcia_contrib'

    def run(self, model):
        res = model.fragment_lcia(self.lcia_method, scenario=self.scenarios)
        return {(obj.name, self.rounding(obj.cumulative_result)) for obj in res.components()} | \
            {('total', self.rounding(res.total()))}


class LciaAggTest(_LciaTest):
    test: str = 'lcia_agg'

    def _make_entry(self, obj):
        return obj.entity.name, self.rounding(obj.cumulative_result)

    def run(self, model):
        res = model.fragment_lcia(self.lcia_method, scenario=self.scenarios, mode='stage')
        return {self._make_entry(c) for c in res.components()} | \
            {('total', self.rounding(res.total()))}


class LciaFlatTest(LciaAggTest):
    test: str = 'lcia_flat'

    def run(self, model):
        res = model.fragment_lcia(self.lcia_method, scenario=self.scenarios, mode='flat')
        return {self._make_entry(c) for c in res.components()} | \
            {('total', self.rounding(res.total()))}


_my_mapping = {
    'cutoff': CutoffsTest,
    'activity': ActivityTest,
    'flows': FragmentFlowsTest,
    'lcia_total': LciaTotalTest,
    'lcia_contrib': LciaContribTest,
    'lcia_agg': LciaAggTest,
    'lcia_flat': LciaFlatTest
}


class LcaTestSuite(BaseModel):
    cutoff: List[CutoffsTest] = []
    activity: List[ActivityTest] = []
    flows: List[FragmentFlowsTest] = []
    lcia_total: List[LciaTotalTest] = []
    lcia_contrib: List[LciaContribTest] = []
    lcia_agg: List[LciaAggTest] = []
    lcia_flat: List[LciaFlatTest] = []
    
    def _traversal_test(self, test, model, *scenarios, **kwargs):
        obj = _my_mapping[test].from_model(model, *scenarios, **kwargs)
        getattr(self, test).append(obj)
        
    def add_cutoff_test(self, model, *args, precision=None):
        self._traversal_test('cutoff', model, *args, precision=precision)

    def add_activity_test(self, model, *args, precision=None):
        self._traversal_test('activity', model, *args, precision=precision)

    def add_flows_test(self, model, *args, precision=None):
        self._traversal_test('flows', model, *args, precision=precision)

    def add_lcia_total_test(self, model, quantity_ref, *args, **kwargs):
        self._traversal_test('lcia_total', model, *args, lcia_method=quantity_ref, **kwargs)

    def add_lcia_contrib_test(self, model, quantity_ref, *args, **kwargs):
        self._traversal_test('lcia_contrib', model, *args, lcia_method=quantity_ref, **kwargs)

    def add_lcia_agg_test(self, model, quantity_ref, *args, **kwargs):
        self._traversal_test('lcia_agg', model, *args, lcia_method=quantity_ref, **kwargs)

    def add_lcia_flat_test(self, model, quantity_ref, *args, **kwargs):
        self._traversal_test('lcia_flat', model, *args, lcia_method=quantity_ref, **kwargs)

    @classmethod
    def from_tests(cls, *tests):
        spec = defaultdict(list)
        for test in tests:
            spec[test.test].append(test)

        return cls(**spec)

    def save(self, filename, overwrite=False):
        if os.path.exists(filename):
            if overwrite is False:
                raise FileExistsError(filename)
        j = self.model_dump_json(indent=2)
        with open(filename, 'w') as fp:
            fp.write(j)
        print('wrote %d tests to %s' % (len(self), filename))

    def __len__(self):
        return sum(len(getattr(self, s)) for s in _my_mapping.keys())

    def run_tests(self, cat, check_origin=None, apply_scenarios=None):
        results = defaultdict(list)
        ps = ct = sk = 0
        for group in _my_mapping.keys():
            tests = getattr(self, group)
            for test in tests:
                print('\n%s' % test.name)
                if check_origin:
                    org = check_origin
                else:
                    org = test.origin
                try:
                    model = cat.query(org).get(test.external_ref)
                except EntityNotFound:
                    sk += 1
                    print('entity %s/%s not found - skipping' % (org, test.external_ref))
                    continue
                if apply_scenarios:
                    hold = model.scenarios
                    model.scenarios = apply_scenarios
                    o = test.check(model)
                    model.scenarios = hold
                else:
                    o = test.check(model)
                results[group].append(o)
                if o:
                    ps += 1
                ct += 1
        print('Passed %d out of %d tests (%d skipped)' % (ps, ct, sk))


def deserialize_test_suite(cat, j):
    """
    This takes a json-serialized LcaTestSuite as input and converts all the entity_refs into live entities prior
    to deserialization

    :param cat:
    :param j:
    :return:
    """
    for tt, tests in j.items():
        if tt.startswith('lcia_'):
            for test in tests:
                e_ref = test.pop('lcia_method')
                try:
                    q = cat.query(e_ref['origin']).get(e_ref['entity_id'])
                except EntityNotFound:
                    q = CatalogRef.from_json(e_ref)
                test['lcia_method'] = q
    return LcaTestSuite(**j)


def run_tests(cat, testfile, check_origin=None):
    with open(testfile) as fp:
        j = json.load(fp)

    suite = deserialize_test_suite(cat, j)

    suite.run_tests(cat, check_origin=check_origin)
    return suite
