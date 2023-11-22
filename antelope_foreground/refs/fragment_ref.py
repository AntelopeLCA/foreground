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

    @property
    def child_flows(self):
        return self._query.child_flows(self)

    def set_name(self, name, **kwargs):
        return self._query.name_fragment(self, name, **kwargs)

    '''
    Process compatibility
    '''
    def inventory(self, scenario=None, **kwargs):
        ios, _ = self.unit_inventory(scenario=scenario, **kwargs)  # in the future, may want to cache this
        return ios_exchanges(ios, ref=self)

    def activity(self, scenario=None, **kwargs):
        """
        Report interior nodes of the fragments and their activity levels-- converse of inventory()
        :return:
        """
        return self._query.activity(self, scenario=scenario, **kwargs)

    def reference_value(self, flow):
        return self._ref_vals[flow.external_ref]

    def tree(self, scenario=None, observed=False):
        return self._query.tree(self, scenario=scenario, observed=observed)

    def show_tree(self, scenario=None, observed=False):
        """
        The old show_tree finally gets properly re-implemented.
        :param scenario:
        :param observed:
        :return:
        """
        tree = self.tree(scenario=scenario, observed=observed)  # these come already sorted
        pnts = []
        cur_stage = ''

        if observed:
            delim = '[]'
        else:
            delim = '()'

        def _pfx():
            return '    | ' * len(pnts)

        def _print_branch(_brnch, _cur_stage):
            if _brnch.group != _cur_stage:
                _cur_stage = _brnch.group
                print('   %s %5s Stage: %s' % (_pfx(), ' ', _cur_stage))
            if _brnch.magnitude is None:
                mag = '--:--'
            else:
                mag = '%7.3g' % _brnch.magnitude
            print('   %s%s%s %.5s %s %s %s%s %s' % (_pfx(), _brnch.node.dirn, _brnch.term_str,
                                                       _brnch.node.entity_uuid,
                                                       delim[0], mag, _brnch.unit, delim[1], _brnch.name))
            return _cur_stage

        for branch in tree:
            if branch.parent is None:
                # print first round
                if len(pnts) > 0:
                    raise ValueError(pnts)
                cur_stage = _print_branch(branch, cur_stage)
                pnts.append(branch.node.entity_id)
            else:
                # handle parents and print subsequent rounds
                if branch.parent != pnts[-1]:  # either up or down
                    if branch.parent in pnts:
                        while branch.parent != pnts[-1]:
                            pnts.pop()
                            print('   %s    x ' % _pfx())  # end cap
                    else:
                        print('   %s [%s]' % (_pfx(), branch.term.unit))  # new generation
                        pnts.append(branch.parent)
                cur_stage = _print_branch(branch, cur_stage)

        # finish up by capping off remaining levels
        while len(pnts) > 0:
            pnts.pop()
            print('   %s    x ' % _pfx())  # end cap

    def traverse(self, scenario=None, **kwargs):
        return self._query.traverse(self, scenario=scenario, **kwargs)

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
        return self._query.fragment_lcia(self, lcia_qty, scenario=scenario, mode=mode, **kwargs)

    def bg_lcia(self, lcia_qty, scenario=None, **kwargs):
        return self.fragment_lcia(self, lcia_qty, scenario=scenario, **kwargs)

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

    def anchors(self, **kwargs):
        return self._query.anchors(self, **kwargs)

    def scenarios(self, **kwargs):
        return self._query.scenarios(self, **kwargs)
