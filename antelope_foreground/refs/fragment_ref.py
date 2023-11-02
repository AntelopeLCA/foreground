from antelope.refs.base import EntityRef
from antelope import ExchangeRef, comp_dir
from ..fragment_flows import group_ios, ios_exchanges
"""
Not sure what to do about Fragment Refs, whether they belong in the main interface. I'd like to think no, but
for now we will just deprecate them and remove functionality,
"""


class FragmentRef(EntityRef):
    """
    Fragments can lookup:
    """
    '''
    def __init__(self, *args, **kwargs):
        super(FragmentRef, self).__init__(*args, **kwargs)
        self._known_scenarios = dict()
    '''
    _etype = 'fragment'
    _ref_field = 'parent'

    def dbg_print(self, *args):
        pass

    def __init__(self, *args, flow=None, direction=None, **kwargs):
        super(FragmentRef, self).__init__(*args, **kwargs)
        self._direction = direction
        self._flow = flow
        self._ref_vals = dict()

    @property
    def direction(self):
        return self._direction

    '''
    @property
    def is_background(self):
        """
        Can't figure out whether it ever makes sense for a fragment ref to be regarded 'background'
        :return:
        """
        return T
    '''

    @property
    def flow(self):
        return self._flow

    @property
    def _addl(self):
        return 'frag'

    @property
    def name(self):
        return self['Name']

    @property
    def is_conserved_parent(self):
        return None

    def top(self):
        return self._query.top(self)

    def set_name(self, name, **kwargs):
        return self._query.name_fragment(self, name, **kwargs)

    '''
    Process compatibility
    '''
    def inventory(self, scenario=None, **kwargs):
        ios, _ = self.unit_inventory(scenario=scenario, **kwargs)  # in the future, may want to cache this
        return ios_exchanges(ios, ref=self)

    def reference_value(self, flow):
        return self._ref_vals[flow.external_ref]

    def traverse(self, scenario=None, **kwargs):
        return self._query.traverse(self.external_ref, scenario=scenario, **kwargs)

    def lci(self, scenario=None):
        """
        TODO
        complex process that will require a recursive traversal and accumulation of LCIs from self + child fragments
        :param scenario:
        :return:
        """
        raise NotImplementedError

    def fragment_lcia(self, lcia_qty, scenario=None, mode=None, **kwargs):
        """

        :param lcia_qty:
        :param scenario:
        :param mode: None, 'detailed', 'flat', 'stage', 'anchor'
        :param kwargs:
        :return:
        """
        return self._query.fragment_lcia(self.external_ref, lcia_qty, scenario=scenario, mode=mode, **kwargs)

    def bg_lcia(self, lcia_qty, scenario=None, **kwargs):
        return self.fragment_lcia(self.external_ref, lcia_qty, scenario=scenario, **kwargs)

    def unit_inventory(self, scenario=None, observed=None):
        """

        :param scenario:
        :param observed: ignored; supplied only for signature consistency
        :return:
        """
        '''
        return NotImplemented
        '''
        if observed is False:
            print('Ignoring false observed flag')
        ffs = self.traverse(scenario=scenario)  # in the future, may want to cache this
        return group_ios(self, ffs)

    def scenarios(self, **kwargs):
        return self._query.scenarios(self.external_ref, **kwargs)
