
from ...implementations import AntelopeForegroundImplementation
from antelope_core.lcia_results import LciaResult
from ...refs.fragment_ref import ParentFragment


class AntelopeV1ForegroundImplementation(AntelopeForegroundImplementation):
    """
    Overrides the default implementation to handle the AntelopeV1 case
    """

    '''
    Implementation Method Overrides
    Unimplemented overrides will simply fallthrough to default:

    def exchanges(self, process, **kwargs):
        pass

    def exchange_values(self, process, flow, direction, termination=None, **kwargs):
        pass

    def inventory(self, process, ref_flow=None, **kwargs):
        pass
    '''
    def top(self, fragment, **kwargs):
        """
        a neutered top() here just returns self
        :param fragment:
        :param kwargs:
        :return:
        """
        if hasattr(fragment, 'external_ref'):
            fragment = fragment.external_ref
        return self._archive.retrieve_or_fetch_entity(fragment)

    def get_reference(self, key):
        raise ParentFragment

    def traverse(self, fragment, scenario=None, **kwargs):
        if hasattr(fragment, 'external_ref'):
            fragment = fragment.external_ref
        if scenario is not None:
            endpoint = 'scenarios/%s/%s/fragmentflows' % (scenario, fragment)
        else:
            endpoint = '%s/fragmentflows' % fragment

        self._archive.fetch_flows(fragment)

        ffs = self._archive.get_endpoint(endpoint)
        for ff in ffs:
            if 'fragmentStageID' in ff:
                ff['StageName'] = self._archive.get_stage_name(ff['fragmentStageID'])
        return [self._archive.make_fragment_flow(ff)
                for ff in sorted(ffs, key=lambda x: ('parentFragmentFlowID' in x, x['fragmentFlowID']))]

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, refresh=False, **kwargs):
        if scenario is None:
            scenario = '1'

        if hasattr(fragment, 'external_ref'):
            fragment = fragment.external_ref

        qi = self._archive.make_interface('quantity')
        lcia_q = qi.get_lcia_quantity(quantity_ref)
        endpoint = 'scenarios/%s/%s/%s/lciaresults' % (scenario, fragment, lcia_q.external_ref)
        lcia_r = self._archive.get_endpoint(endpoint, cache=False)
        if lcia_r is None or (isinstance(lcia_r, list) and all(i is None for i in lcia_r)):
            res = LciaResult(lcia_q, scenario=scenario)
            return res

        res = LciaResult(lcia_q, scenario=lcia_r.pop('scenarioID'))
        total = lcia_r.pop('total')

        for component in lcia_r['lciaScore']:
            qi.add_lcia_component(res, component)

        qi.check_total(res.total(), total)

        return res


