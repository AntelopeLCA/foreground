from antelope.refs.base import EntityRef
from antelope import ExchangeRef, comp_dir
from ..fragment_flows import group_ios
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

    def __init__(self, *args, **kwargs):
        super(FragmentRef, self).__init__(*args, **kwargs)
        self._direction = None
        self._flow = None
        self._isset = False
        self._ref_vals = dict()

    def set_config(self, flow, direction):
        if self._isset:
            raise AttributeError('Fragment Ref is already specified!')
        self._isset = True
        self._flow = flow
        self._direction = direction

    def _retrieve_config(self):
        rx = self.reference_entity[0]
        self.set_config(rx.flow, comp_dir(rx.direction))

    @property
    def direction(self):
        if not self._isset:
            self._retrieve_config()
        return self._direction

    @property
    def is_background(self):
        """
        Can't figure out whether it ever makes sense for a fragment ref to be regarded 'background'
        :return:
        """
        return False

    @property
    def flow(self):
        if not self._isset:
            self._retrieve_config()
        return self._flow

    @property
    def _addl(self):
        return 'frag'

    @property
    def name(self):
        if self.external_ref is None:
            return self['Name']
        return self.external_ref

    @property
    def is_conserved_parent(self):
        return None

    def top(self):
        return self

    def set_name(self, name, **kwargs):
        return self._query.name_fragment(self, name, **kwargs)

    '''
    Process compatibility
    '''
    def inventory(self, scenario=None, **kwargs):
        ffs = self.traverse(scenario=scenario)  # in the future, may want to cache this
        ios, nodes = group_ios(self, ffs, **kwargs)
        frag_exchs = []
        for f in ios:
            is_ref = (f.fragment.flow == self.flow and f.fragment.direction == comp_dir(self.direction))

            xv = ExchangeRef(self, f.fragment.flow, f.fragment.direction, value=f.magnitude, is_reference=is_ref)
            frag_exchs.append(xv)
            if scenario is None:
                self._ref_vals[xv.flow.external_ref] = f.magnitude
        return sorted(frag_exchs, key=lambda x: (x.direction == 'Input', x.value), reverse=True)

    def reference_value(self, flow):
        return self._ref_vals[flow.external_ref]

    def traverse(self, scenario=None, **kwargs):
        return self._query.traverse(self.external_ref, scenario=scenario, **kwargs)

    def fragment_lcia(self, lcia_qty, scenario=None, **kwargs):
        return self._query.fragment_lcia(self.external_ref, lcia_qty, scenario=scenario, **kwargs)

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
