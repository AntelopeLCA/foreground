"""


"""

import uuid
# from collections import defaultdict

from antelope import comp_dir, check_direction, PropertyExists, CatalogRef, RxRef, QuantityRequired

from ..fragment_flows import group_ios, FragmentFlow, ios_exchanges, frag_flow_lcia
from antelope_core.entities import LcEntity, LcFlow
from antelope_core.exchanges import ExchangeValue
# from lcatools.interact import ifinput, parse_math
from ..terminations import FlowTermination, MissingFlow
from ..foreground_query import MissingResource

class InvalidParentChild(Exception):
    pass


class FoundBalanceFlow(Exception):
    """
    raised if a fragment attempts to traverse a balance flow the normal way
    """
    pass


class BalanceAlreadySet(Exception):
    pass


class CacheAlreadySet(Exception):
    pass


class ScenarioConflict(Exception):
    pass


class DependentFragment(Exception):
    pass


class ZeroInboundExchange(Exception):
    pass


def _new_evs():
    d = dict()  # should be a LowerDict? should scenario names be case sensitive?
    d[0] = 1.0
    d[1] = 0.0
    return d


class LcFragment(LcEntity):
    """

    """

    @classmethod
    def new(cls, name, *args, verbose=False, **kwargs):
        """
        :param name: the name of the fragment
        :param args: need flow and direction
        :param verbose: print when a fragment is created
        :param kwargs: parent, exchange_value, private, balance_flow, background, termination
        :return:
        """
        if verbose:
            print('LcFragment - Name: %s:' % name, 0)  # this will never run since the constructor does not set dbg
        return cls(uuid.uuid4(), *args, Name=name, **kwargs)

    _ref_field = 'parent'

    _new_fields = ['StageName']

    @classmethod
    def from_json(cls, fg, j):
        if j['parent'] is None or j['parent'].lower() == 'none':
            parent = None
        else:
            parent = fg[j['parent']]
            if parent is None:
                print('warning: parent %s returned None' % j['parent'])
        flow = fg[j['flow']]
        if flow is None:
            try:
                org, ext = j['flow'].split('/')
                flow = fg.catalog_ref(org, ext, entity_type='flow')
            except ValueError:
                print('%s: Flow %s not found in foreground %s' % (j['entityId'], j['flow'], fg.ref))
                flow = LcFlow(j['flow'], Name=j['tags']['Name'], Compartment=['Intermediate Flows', 'Fragments'],
                              referenceQuantity=fg._catalog.get_canonical('mass'))
                fg.add(flow)
        frag = cls(j['entityId'], flow, j['direction'], origin=fg.ref, parent=parent,
                   exchange_value=j['exchangeValues'].pop('0'),
                   private=j['isPrivate'],
                   balance_flow=j['isBalanceFlow'])
        if j['externalId'] != j['entityId']:
            frag.external_ref = j['externalId']
        frag._exchange_values[1] = j['exchangeValues'].pop('1')
        for i, v in j['exchangeValues'].items():
            if i.find('____') >= 0:
                i = tuple(i.split('____'))
            frag._exchange_values[i] = v
            # frag.set_exchange_value(i, v)
        for tag, val in j['tags'].items():
            frag[tag] = val  # just a fragtag group of values
        return frag

    def finish_json_load(self, fg, j):
        # self.reference_entity = catalog[0][j['parent']]
        for k, v in j['terminations'].items():
            if k == 'default' or k == 'null':
                self.term_from_json(fg, None, v)
            else:
                self.term_from_json(fg, k, v)

    @classmethod
    def from_exchange(cls, parent, exchange):
        """
        This method creates a child flow, positioning the parent node as the 'process' component of the exchange
        and using the exchange's 'flow' and 'direction' components to define the child flow.  If the exchange
        also includes a 'termination', then that is used to automatically terminate the child flow.
        :param parent:
        :param exchange:
        :return:
        """
        frag = cls(uuid.uuid4(), exchange.flow, exchange.direction, parent=parent,
                   exchange_value=exchange.value, Name=exchange.flow['Name'])

        if exchange.termination is not None:
            frag.terminate(CatalogRef(exchange.flow.origin, exchange.termination, entity_type='process'),
                           term_flow=exchange.flow)
        return frag

    def __init__(self, the_uuid, flow, direction, parent=None,
                 exchange_value=1.0,
                 units=None,
                 private=False,
                 balance_flow=False,
                 background=False,
                 termination=None,
                 term_flow=None,
                 external_ref=None,
                 observe=None,
                 descend=None,
                 **kwargs):
        """
        Required params:
        :param the_uuid: use .new(Name, ...) for a random UUID
        :param flow: an LcFlow (catalog ref doesn't cut it)
        :param direction:
        :param parent:
        :param exchange_value: auto-set- cached; can only be set once
        :param units: to convert exchange value, if supplied
        :param private: forces aggregation of subfragments (not currently used)
        :param balance_flow: if true, exch val is always ignored and calculated based on parent
        :param background: [[DEPRECATED / to be ignored]] if true, ends traversal
        :param termination: specify the fragment's default termination
        :param term_flow: specify the term_flow (ignored if termination is None)
        :param observe: [None] if True, assign observed_ev to match cached_ev
        :param descend: [None] if a termination is provided, whether to set its descend flag
        :param kwargs:
        """

        self.__dbg_threshold = -1  # higher number is more verbose
        self._exchange_values = _new_evs()
        self._balance_child = None
        self._private = private
        # self._background = background
        self._is_balance = False
        self._child_flows = list()

        super(LcFragment, self).__init__('fragment', external_ref, entity_uuid=the_uuid, **kwargs)
        if self._external_ref == self._uuid:
            self._external_ref = None  # reset this

        if parent is not None:
            self.set_parent(parent)

        assert flow.entity_type == 'flow', '%s %s' % (flow.entity_type, flow.link)
        # # this is a problem when referencing a flow with unknown origin / no query
        # assert flow.reference_entity.entity_type == 'quantity'
        self.flow = flow
        self.direction = check_direction(direction)  # w.r.t. parent

        self._terminations = dict()
        self._terminations[None] = FlowTermination.null(self)

        # set termination and StageName
        if termination is None:
            if 'StageName' not in self._d:
                self._d['StageName'] = ''
        else:
            self._terminations[None] = FlowTermination(self, termination, term_flow=term_flow, descend=descend)
            if 'StageName' not in self._d:
                stagename = ''
                try:
                    stagename = termination['Name']
                except (TypeError, KeyError):
                    try:
                        stagename = termination.name
                    except AttributeError:
                        pass
                finally:
                    self._d['StageName'] = stagename
        # set EV last
        if balance_flow:
            self.set_balance_flow()
        else:
            if exchange_value is not None:
                self.set_exchange_value(0, exchange_value, units=units)
            if observe:
                self.observed_ev = self.cached_ev

    def __hash__(self):
        """
        Fragments must use UUID as hash because the link is mutable
        :return:
        """
        if self._origin is None:
            raise AttributeError('Origin not set!')
        return hash('%s/%s' % (self.origin, self.uuid))

    @property
    def external_ref(self):
        if self._external_ref is None:
            return self._uuid
        return self._external_ref

    @external_ref.setter
    def external_ref(self, ref):
        """
        Specify how the entity is referred to in the source dataset. If this is unset, the UUID is assumed
        to be used externally.
        :param ref:
        :return:
        """
        if self._external_ref is None:
            if ref != self.uuid:  # don't bother setting if it's the same as the UUID
                self._external_ref = ref
        else:
            raise PropertyExists('External Ref already set to %s' % self._external_ref)

    def de_name(self):
        """
        Remove a fragment's name
        :return:
        """
        self._external_ref = None

    def set_debug_threshold(self, level):
        self.__dbg_threshold = level

    def dbg_print(self, qwer, level=1):
        if level < self.__dbg_threshold:
            print('%.3s %s' % (self.uuid, qwer))

    def reference(self, flow=None):
        """
        For process interoperability
        :return:
        """
        rx = RxRef(self, self.flow, comp_dir(self.direction), self.get('Comment', None), value=self.observed_ev)
        if flow is not None:
            if not rx.flow.match(flow):
                raise ValueError('%.5s: Supplied flow %s does not match fragment' % (self.uuid, flow))
        return rx

    def make_ref(self, query):
        """
        We do NOT want to make local fragments into refs-- but we DO want to make remote fragments into refs. so
        we simply neuter the workhorse function here.
        :param query:
        :return:
        """
        '''
        ref = super(LcFragment, self).make_ref(query)
        ref.set_config(self.flow.make_ref(query.cascade(self.flow.origin)), self.direction)
        return ref
        '''
        return self

    def top(self):
        if self.reference_entity is None:
            return self
        return self.reference_entity.top()

    def set_parent(self, parent):
        if self.reference_entity is not None:
            self.unset_parent()
        if self.origin != parent.origin:
            if self.origin is None:
                self.origin = parent.origin
            else:
                raise AttributeError('Origin mismatch: parent (%s) vs child (%s)' % (parent.origin, self.origin))
        self._set_reference(parent)
        parent.add_child(self)

    def unset_parent(self):
        if self.is_balance:
            self.unset_balance_flow()
        self.reference_entity.remove_child(self)
        self._set_reference(None)

    '''
    def has_child(self, flow, direction, termination=None):
        for c in self.child_flows:
            if c.flow == flow and c.direction == direction:
                term = c.term
                if term.is_null:
                    if termination is None:
                        return True
                else:
                    if term.is_process and term.term_node.external_ref == termination:
                        return True
                    # this looks a bit ridiculous but I think it's right
                    if term.is_frag and term.term_node.term.term_node.external_ref == termination:
                        return True
        return False
    '''

    def add_child(self, child):
        """
        This should only be called from the child's set_parent function
        :param child:
        :return:
        """
        # if child.reference_entity is not self:
        #     raise InvalidParentChild('Fragment should list parent as reference entity')
        if child not in self._child_flows:
            self._child_flows.append(child)
        if self.term.is_null:  # formerly to_foreground()
            self.terminate(self)
        for term in self._terminations.values():
            term.clear_score_cache()

    def remove_child(self, child):
        """
        This should only be called from the child's unset_parent function
        :param child:
        :return:
        """
        if child.reference_entity is not self:
            raise InvalidParentChild('Fragment is not a child')
        self._child_flows.remove(child)
        if len(self._child_flows) == 0:
            if self.term.term_node is self:
                self.clear_termination()
        for term in self._terminations.values():
            term.clear_score_cache()

    @property
    def child_flows(self):
        for k in self._child_flows:  # sorted(self._child_flows, key=lambda x: x.uuid):
            yield k

    def children_with_flow(self, flow, direction=None, termination=None, recurse=False):
        for k in self._child_flows:
            if k.flow == flow:
                if direction is not None:
                    if k.direction != direction:
                        continue
                if termination is not None:
                    if k.term.term_node != termination:
                        continue
                yield k
            if recurse:  # depth-first
                for z in k.children_with_flow(flow, direction, recurse=recurse):
                    yield z

    @property
    def parent(self):
        return self.reference_entity

    @property
    def is_reference(self):
        return self.reference_entity is None

    @property
    def term(self):
        return self._terminations[None]

    @property
    def name(self):
        if self._external_ref is None:
            return self['Name']
        return self.external_ref

    @property
    def dirn(self):
        return {
            'Input': '-<-',
            'Output': '=>='
        }[self.direction]

    def _serialize_evs(self):
        evs = dict()
        for k, v in self._exchange_values.items():
            if k is None:
                evs["0"] = v
            elif isinstance(k, int):
                evs[str(k)] = v
            else:
                evs[k] = v
        return evs

    def _serialize_terms(self, save_unit_scores=False):
        terms = dict()
        for k, v in self._terminations.items():
            if k is None:
                terms['default'] = v.serialize(save_unit_scores=save_unit_scores)
            else:
                terms[k] = v.serialize()
        return terms

    def serialize(self, save_unit_scores=False, domesticate=True, **kwargs):
        j = super(LcFragment, self).serialize(domesticate=True, **kwargs)  # once you save a fragment, it's yours

        if self.flow.origin == self.origin:
            f_e_r = self.flow.external_ref
        else:
            f_e_r = self.flow.link

        j.update({
            'entityId': self.uuid,
            'flow': f_e_r,
            'direction': self.direction,
            'isPrivate': self._private,
            'isBackground': self.is_background,  # descriptive only
            'isBalanceFlow': self.is_balance,
            'exchangeValues': self._serialize_evs(),
            'terminations': self._serialize_terms(save_unit_scores=save_unit_scores),
            'tags': self._d
        })
        for k in self._d.keys():
            j.pop(k, None)  # we put these together in tags
        return j

    @property
    def unit(self):
        """
        used for formatting the fragment in display
        :return:
        """
        if self.reference_entity is None:
            return '%4g %s' % (self.cached_ev, self.flow.unit)
        return self.term.unit

    def __str__(self):
        if self.reference_entity is None:
            if self.is_background:
                re = '(B) ref'
            else:
                re = ' ** ref'
        else:
            re = self.reference_entity.uuid[:7]
        if self.external_ref == self.uuid:
            extname = ''
        else:
            extname = '{%s}' % self.external_ref

        return '(%s) %s %.5s %s %s  [%s] %s %s' % (re, self.dirn, self.uuid, self.dirn, self.term,
                                                   self.unit, self['Name'], extname)

    def show(self):
        print('%s' % self)
        super(LcFragment, self).show()
        evs = list(self._exchange_values.keys())
        evs.remove(0)
        evs.remove(1)
        print('Exchange values: ')
        print('%20.20s: %g' % ('Cached', self.cached_ev))
        print('%20.20s: %g' % ('Observed', self.observed_ev))
        for k in evs:
            print('%20.20s: %g' % (k, self.exchange_value(k)))
        if self.is_balance:
            print('\nBalance flow: True (%s)' % self.flow.reference_entity)
        else:
            print('\nBalance flow: False')
        print('Terminations: ')
        print('%20s  %s' % ('Scenario', 'Termination'))
        for k, v in self._terminations.items():
            if v.term_node is self:
                print('%20.20s: %s Foreground' % (k, v))
            else:
                if v.descend:
                    desc = '     '
                else:
                    desc = '(agg)'
                print('%20.20s: %s %s %s' % (k, v, desc, v.term_node))

    def show_tree(self, scenario=None, observed=False, prefix=''):
        """
        THIS WHOLE FUNCTION is deprecated-- need to use live traversal results and not recurse over static data
        :param scenario:
        :param observed:
        :param prefix:
        :return:
        """
        children = [c for c in self.child_flows]
        term = self.termination(scenario)
        if len(children) > 0 and term.is_null:
            raise InvalidParentChild('null-terminated fragment %.7s has children' % self.uuid)

        delim = '()'
        if self.observed_ev != 0.0:
            delim = '[]'
        if not(observed and self.observed_ev == 0.0):
            # when doing the observed mode, don't print zero results
            print('   %s%s%s %.5s %s%s%7.3g %s%s %s' % (prefix, self.dirn, term, self.uuid,
                                                        delim[0],
                                                        self._mod(scenario),
                                                        self.exchange_value(scenario, observed=observed) or 0.0,
                                                        self.flow.unit,
                                                        delim[1],
                                                        self['Name']))
        # print fragment reference
        latest_stage = ''
        if len(children) > 0:
            print('   %s [%s] %s' % (prefix, term.unit, self['Name']))
            prefix += '    | '
            for c in sorted(children, key=lambda x: (x['StageName'], not x.term.is_null,
                                                     x.term.is_bg or x.term.term_is_bg)):
                if not c.balance_flow:
                    if observed and c.exchange_value(scenario, observed=observed) == 0:
                        continue
                if c['StageName'] != latest_stage:
                    latest_stage = c['StageName']
                    print('   %s %5s Stage: %s' % (prefix, ' ', latest_stage))
                c.show_tree(scenario=scenario, observed=observed, prefix=prefix)
            prefix = prefix[:-3] + ' x '
            print('   %s' % prefix)

    @property
    def cached_ev(self):
        ev = self._exchange_values[0]  # or 1.0  ## Why??? we need to allow zero values
        if ev is None:
            ev = 0.0
        return ev

    @cached_ev.setter
    def cached_ev(self, value):
        if self.cached_ev != 1.0:
            raise CacheAlreadySet('Set Value: %g (new: %g)' % (self.cached_ev, value))
        if value == self.cached_ev:
            return
        self._exchange_values[0] = value

    def reset_cache(self):
        """
        this must be done explicitly
        :return:
        """
        self._exchange_values[0] = 1.0

    def scale_evs(self, factor):
        """
        needed when foregrounding terminations
        :param factor:
        :return:
        """
        for k, v in self._exchange_values.items():
            self._exchange_values[k] = v * factor

    def clear_evs(self):
        self._exchange_values = _new_evs()

    @property
    def observed_ev(self):
        """

        :return: the observed exchange value
        """
        ''' # this is bogus
        ev = self._exchange_values[1]
        if self.reference_entity is None and ev == 0:  # now with named = observed, shouldn't every frag be observed?
            ev = self._exchange_values[0]
        return ev
        '''
        return self._exchange_values[1]

    def observable(self, scenario=None):
        return self._check_observability(scenario=scenario)

    def _check_observability(self, scenario=None):
        if self.reference_entity is None:
            return True
        elif self.is_balance:
            self.dbg_print('observability: value set by balance.')
            return False
        elif self.reference_entity.termination(scenario).is_subfrag:
            self.dbg_print('observability: value set during traversal')
            return False
        else:
            return True

    @observed_ev.setter
    def observed_ev(self, value):
        if self._check_observability(None):
            self._exchange_values[1] = value

    def _observe(self, scenario=None, value=None, units=None):
        """
        no reason to have an interactive observe engine in an entity definition
        :param scenario:
        :return:
        """
        if value is None:
            '''
            if scenario is None:
                prompt = 'Observed value'
            else:
                prompt = 'Scenario value'

            print('%s' % self)
            print(' Cached EV: %6.4g\n Observed EV: %6.4g [%s]' % (self.cached_ev, self.observed_ev, self.flow.unit))
            if scenario is None:
                string_ev = '%10g' % self.observed_ev
            else:
                string_ev = '%10g' % self.exchange_value(scenario)
                print(' Scenario EV: %s [%s]' % (string_ev,
                                                 self.flow.unit))

            val = ifinput('%s ("=" to use cached): ' % prompt, string_ev)

            if val != string_ev:
                if val == '=':
                    value = self.cached_ev
                else:
                    value = parse_math(val)
            '''
            raise ValueError('%.5s: Either supply an observed value or accept_all=True' % self.uuid)

        if scenario is None:
            self.set_exchange_value(1, value, units=units)
        else:
            self.set_exchange_value(scenario, value, units=units)

    def _auto_observe(self, scenario=None):
        if scenario is None:
            self.observed_ev = self.cached_ev
        else:
            self.set_exchange_value(scenario, self.cached_ev)

    def observe(self, value=None, units=None, scenario=None, accept_all=False, recurse=True, _traverse=True):
        """
        Report the fragment's observed exchange value and assign it a name
        if fragment is a balance flow or if fragment is a child of a subfragment (for the specified scenario), then
         the ev is set during traversal and may not be observed.

        :param value: the observed exchange value (if omitted, and accept_all is False, observe interactively)
        :param units: optional unit for observed value
        :param scenario:
        :param accept_all: whether to automatically apply the cached EV to the observation
        :param recurse: whether to observe child fragments. automatically False if a value is supplied
        :param _traverse: internal param. used to only traverse the top-most fragment.
        :return:
        """
        if self._check_observability(scenario=scenario):
            if accept_all and (value is None):  # ignore
                self._auto_observe(scenario=scenario)
            else:
                self._observe(scenario=scenario, value=value, units=units)

        if recurse and (value is None):
            for c in self.child_flows:
                c.observe(scenario=scenario, accept_all=accept_all, recurse=True, _traverse=False)

        if _traverse:
            self.traverse(scenario, observed=True)

    @property
    def is_background(self):
        return len(self._child_flows) == 0  # self._background

    def scenarios(self, recurse=True):
        """
        Generate a list of scenarios known to the fragment.

        :param recurse: [True] By default, traverse all child flows, including subfragments. If False, only report
         the present fragment
         filter out internal scenarios (start with '__') from recursive queries but not from the top level
        :return:
        """
        scenarios = set(list(self._exchange_values.keys()))
        for scen, term in self._terminations.items():
            scenarios.add(scen)
            if recurse and term.is_subfrag:
                for k in term.term_node.scenarios(recurse=True):
                    if str(k).startswith('__'):
                        continue
                    scenarios.add(k)

        if recurse:
            for c in self.child_flows:
                for k in c.scenarios(recurse=True):
                    scenarios.add(k)

        scenarios -= {0, 1, None}
        for k in sorted(scenarios):
            yield k

    def clear_scenarios(self, terminations=True):
        sc = [k for k in self._exchange_values.keys() if k not in (0, 1)]
        for s in sc:
            self._exchange_values.pop(s)
        if terminations:
            sc = [k for k in self._terminations.keys() if k is not None]
            for s in sc:
                self._terminations.pop(s)

    def _match_scenario_ev(self, scenario):
        """
        If *any* scenario is specified, we return either a match or the observed ev.

        Special case: if the matched scenario begins with 'norm' AND the current fragment is a reference fragment,
        then interpret the scenario as a normalization factor and REMOVE it from subsequent traversals to prevent
        double-norming. Not totally convinced this is a good idea, but it is useful for some select circumstances.

        Plus, double-norming (in recursive descent) is objectively wrong-- there is no circumstance when it is right.
        :param scenario:
        :return:
        """
        if scenario is None:
            return None
        if isinstance(scenario, set):
            match = [scen for scen in filter(None, scenario) if scen in self._exchange_values.keys()]
            if len(match) == 0:
                return 1
            elif len(match) > 1:
                raise ScenarioConflict('fragment: %s\nexchange value matches: %s' % (self, match))
            m = match[0]
            if str(m).startswith('norm') and self.parent is None:
                print('Applying and removing one-time normalization scenario %s' % m)
                # self.dbg_print('Applying and removing one-time normalization scenario %s' % m, level=0)
                scenario.remove(m)
            return m
        if scenario in self._exchange_values.keys():
            return scenario
        return 1

    def _match_scenario_term(self, scenario):
        if scenario == 0 or scenario == '0' or scenario is None:
            return None
        if isinstance(scenario, set):
            match = [scen for scen in filter(None, scenario) if scen in self._terminations.keys()]
            if len(match) == 0:
                return None
            elif len(match) > 1:
                raise ScenarioConflict('fragment: %s\ntermination matches: %s' % (self, match))
            return match[0]
        if scenario in self._terminations.keys():
            return scenario
        return None

    def exchange_value(self, scenario=None, observed=False):
        """

        :param scenario: None, a string, or a tuple of strings. If tuple, raises error if more than one match.
        :param observed:
        :return:
        """
        if scenario is None:
            if observed:
                ev = self.observed_ev
            else:
                ev = self.cached_ev
        else:
            if isinstance(scenario, list) or isinstance(scenario, tuple):
                scenario = set(scenario)
            match = self._match_scenario_ev(scenario)
            if match is None:
                ev = self.observed_ev
            else:
                ev = self._exchange_values[match]
        if ev is None:
            return 0.0
        return ev

    def parameters(self):
        p = {'origin': self.origin, 'parameter': self.external_ref, 'flow_unit': self.flow.unit}
        if self.observable():
            p['default'] = self.observed_ev
        for k, v in self._exchange_values.items():
            if k in (0, 1):  # this obviously needs to be redone
                continue
            if self.observable(k):
                p[k] = v
        return p

    def _mod(self, scenario):
        """
        Returns a visual indicator that reports whether the fragment's exchange_value or termination are affected
        under a given scenario.
        :param scenario:
        :return: ' ' no effect
                 '=' balance flow
                 '+' termination affected under scenario
                 '*' exchange value affected under scenario
                 '%' both termination and exchange value affected under scenario
        """
        if self.is_balance:
            return '='
        match_e = self._match_scenario_ev(scenario)
        match_t = self._match_scenario_term(scenario)
        if match_e is None or self.exchange_value(match_e) == self.cached_ev:
            if match_t is None:
                return ' '  # no scenario
            return '+'  # term scenario
        if match_t is None:
            return '*'  # ev scenario
        return '%'  # both scenario

    def set_exchange_value(self, scenario, value, units=None):
        """
        The exchange value may not be set on a reference fragment UNLESS the termination for the named scenario is
        to foreground- in which case the term's inbound_ev is set instead. (and a term is created if none exists)
        :param scenario:
        :param value: if 'None', un-set any observation for the given scenario
        :param units: unit string, if value is to be converted from non-reference units
        :return:
        """
        if value is None:
            if scenario not in {1, '1', 0, '0', None}:
                v = self._exchange_values.pop(scenario, None)
                if v:
                    self.dbg_print('Removed observation %g for scenario %s' % (v, scenario), level=0)
            return
        if not self._check_observability(scenario=scenario):
            raise DependentFragment('Fragment exchange value set during traversal')
        if isinstance(scenario, tuple) or isinstance(scenario, set):
            raise ScenarioConflict('Set EV must specify single scenario')

        value = float(value)

        if units is not None and len(units) > 0:
            try:
                value *= self.flow.reference_entity.convert(units)
            except KeyError:
                print('Flow conversion error: %5.5s: %s (%s)' % (self.uuid, self.flow.reference_entity, units))
                value = 0.0

        if scenario == 0 or scenario == '0' or scenario == 'cached' or scenario is None:
            self._exchange_values[0] = value
        elif scenario == 1 or scenario == '1' or scenario == 'observed':
            self._exchange_values[1] = value
        else:
            self._exchange_values[scenario] = value

    @property
    def conserved(self):
        return bool(self.balance_magnitude)  # None or 0 -> False

    @property
    def balance_flow(self):
        return self._balance_child

    @property
    def is_balance(self):
        return self._is_balance

    def reverse_direction(self):
        """
        Changes the direction of a fragment to its complement, since the direction of the fragment flow is arbitrary.
        negates all stored exchange values, so as to have no effect on traversal computations.
        :return:
        """
        d = dict()
        for k, v in self._exchange_values.items():
            d[k] = -1 * v
        self.direction = comp_dir(self.direction)
        self._exchange_values = d

    def set_balance_flow(self):
        """
        A balance flow balances its own reference quantity.
        :return:
        """
        if self.reference_entity is None:
            raise InvalidParentChild('Reference flow cannot be a balance flow')
        if self.is_balance is False:
            self.reference_entity.set_conservation_child(self)
            self._is_balance = True

    def unset_balance_flow(self):
        if self.is_balance:
            self.reference_entity.unset_conservation_child()
            self._is_balance = False

    def set_conservation_child(self, child):
        if child.reference_entity != self:
            raise InvalidParentChild
        if self.is_conserved_parent and (child is not self._balance_child):
            print('%.5s conserving %s\nversus %s' % (self.uuid, self._balance_child, child))
            raise BalanceAlreadySet
        self._balance_child = child
        if self.balance_magnitude == 0:
            self.dbg_print('%.5s Notice: zero balance for conserved quantity %s' % (self.uuid,
                                                                                    self.conserved_quantity))
        self.dbg_print('setting balance from %.5s: %s' % (child.uuid, self._balance_child))

    @property
    def is_conserved_parent(self):
        return self._balance_child is not None

    def unset_conservation_child(self):
        self._balance_child = None

    @property
    def conserved_quantity(self):
        if self._balance_child is None:
            return None
        else:
            return self._balance_child.flow.reference_entity

    @property
    def balance_magnitude(self):
        """
        The cf of the current flow in balanced units (if a balance flow exists)
        :return:
        """
        if self._balance_child is None:
            return None
        else:
            try:
                return self._balance_child.flow.reference_entity.cf(self.flow)
            except (QuantityRequired, MissingResource):
                return 0.0

    '''
    def balance(self, scenario=None, observed=False):
        """
        display a balance the inputs and outputs from a fragment termination.  This probably needs to be reimagined and
        rewritten
        :param scenario:
        :param observed:
        :return: a dict of quantities to balance magnitudes (positive = input to term node)
        """
        qs = defaultdict(float)
        if self.reference_entity is None:
            in_ex = self.exchange_value(scenario, observed=observed)
        else:
            in_ex = 1.0
        for cf in self.flow.reference_entity.profile(self.flow):
            if cf.value is not None:
                if self.direction == 'Input':  # output from term
                    qs[cf.quantity] -= cf.value * in_ex
                else:
                    qs[cf.quantity] += cf.value * in_ex
        for c in self.child_flows:
            for cf in c.flow.reference_entity.profile(c.flow):
                mag = c.exchange_value(scenario, observed=observed) * (cf.value or 0.0)
                if mag != 0:
                    if c.direction == 'Output':
                        qs[cf.quantity] -= mag
                    else:
                        qs[cf.quantity] += mag

        for k, v in qs.items():
            print('%10.4g %s' % (v, k))
        return qs

    def show_balance(self, quantity=None, scenario=None, observed=False):
        def _p_line(f, m, d):
            try:
                # will fail if m is None or non-number
                print(' %+10.4g  %6s  %.5s %s' % (m, d, f.uuid, f['Name']))
            finally:
                pass

        if quantity is None:
            quantity = self.flow.reference_entity

        print('%s' % quantity)
        mag = quantity.cf(self.flow).value
        if self.reference_entity is None:
            mag *= self.exchange_value(scenario, observed=observed)
        if self.direction == 'Input':
            mag *= -1

        net = mag

        _p_line(self, mag, comp_dir(self.direction))

        for c in sorted(self.child_flows, key=lambda x: x.direction):
            mag = c.exchange_value(scenario, observed=observed) * quantity.cf(c.flow).value
            if c.direction == 'Output':
                mag *= -1
            if mag is None or mag != 0:
                _p_line(c, mag, c.direction)
            net += mag

        print('----------\n %+10.4g net' % net)
    '''

    '''
    Terminations and related functions
    '''

    def terminate(self, term_node, scenario=None, direction=None, **kwargs):
        """
        specify the fragment's termination in a given scenario.
        :param term_node: The thing that terminates the flow
        :param scenario:
        :param direction: outmoded option (can still use _direction if kluge is needed)
        :param kwargs: term_flow, descend
        :return:
        """
        if scenario in ('cached', 'observed'):
            raise ValueError('scenario cannot use reserved name: %s' % scenario)

        if direction is not None:
            raise NotImplementedError('Flow Termination Directions are not supposed to be specified by hand')
        if isinstance(scenario, tuple) or isinstance(scenario, set):
            raise ScenarioConflict('Set termination must specify single scenario')
        if scenario is not None and scenario in self._terminations:
            if not self._terminations[scenario].is_null:
                raise CacheAlreadySet('Scenario termination already set. use clear_termination()')

        if scenario is None and term_node in self._terminations:
            # shortcut: assign an existing scenario to be default  ## DWR? this is surely nonstandard-
            # causes namespace conflicts btwn scenario and external_ref, but not really because the argument is
            # supposed to be a node. supplying txt as an argument is nonstandard- so it's clearly a hack. eh.
            self._terminations[None] = self._terminations[term_node]
            return self._terminations[term_node]

        termination = FlowTermination(self, term_node, **kwargs)
        self._terminations[scenario] = termination
        if scenario is None:
            if self['StageName'] == '' and not termination.is_null:
                if termination.is_frag:
                    self['StageName'] = termination.term_node['StageName']
                elif termination.is_context:
                    self['StageName'] = termination.term_node.name
                else:
                    try:
                        self['StageName'] = termination.term_node['Name']
                    except (KeyError, TypeError, IndexError):
                        print('%.5s StageName failed %s' % (self.uuid, termination.term_node))
                        self['StageName'] = termination.term_node.name
        return termination

    def clear_termination(self, scenario=None):
        self._terminations[scenario] = FlowTermination.null(self)

    '''
    def to_foreground(self, scenario=None):
        """
        make the fragment a foreground node. This is done by setting the termination to self (only if the term is
        currently null).  A foreground node
        may not be a background node (obv.)  Note: a foreground node will not act as an emission during traversal and
        fragment LCIA (it must be terminated to a context), but it can have observed unit scores.
        However, it will not show up as a cutoff.  foreground() fragments can conceal flows.
        :param scenario:
        :return:
        """
        # self.unset_background()
        if self.termination(scenario).is_null:
            self.terminate(self, scenario=scenario)
    '''

    '''
    def unset_background(self):
        if self._background is True:
            for term in self._terminations.values():
                term.clear_score_cache()
        self._background = False

    def set_background(self):
        for scenario, term in self._terminations.items():
            if not term.is_null:
                if term.term_node.entity_type == 'fragment':
                    raise ScenarioConflict('Cannot bg: Terminated to fragment in Scenario %s' % scenario)
        if self._background is False:
            for term in self._terminations.values():
                term.clear_score_cache()
        self._background = True
    '''

    def term_from_json(self, fg, scenario, j):
        if isinstance(scenario, tuple):
            raise ScenarioConflict('Set termination must specify single scenario')
        self._terminations[scenario] = FlowTermination.from_json(self, fg, scenario, j)

    def termination(self, scenario=None):
        match = self._match_scenario_term(scenario)
        if match in self._terminations.keys():
            return self._terminations[match]
        # if None in self._terminations.keys():  # this should be superfluous, as match will be None
        #     return self._terminations[None]
        raise ScenarioConflict('This should never happen - No match found for %s' % scenario)

    def terminations(self):
        return self._terminations.items()

    '''
    def set_child_exchanges(self, scenario=None, reset_cache=False):
        """
        This is really client code, doesn't use any private capabilities
        Set exchange values of child flows based on inventory data for the given scenario.  The termination must be
         a foreground process.

        In order for this function to work, flows in the node's exchanges have to have the SAME external_ref as the
        child flows, though origins can differ.  There is no other way for the exchanges to be set automatically from
        the inventory.  Requiring that the flows have the same name, CAS number, compartment, etc. is too fragile /
        arbitrary.  The external refs must match.

        This works out okay for databases that use a consistent set of flows internally -- ILCD, thinkstep, and
        ecoinvent all seem to have that characteristic but ask me again in a year.

        To automatically set child exchanges for different scenarios that use processes from different databases,
        encapsulate each term node inside a sub-fragment, and then specify different subfragment terminations for the
        different scenarios.  Then, map each input / output in the sub-fragment to the correct foreground flow using
        a conserving child flow.

        In that case, the exchange values will be set during traversal, and each sub-fragment's internal exchange
        values can be set automatically using set_child_exchanges.

        :param scenario: [None] for the default scenario, set observed ev
        :param reset_cache: [False] if True, for the default scenario set cached ev
        :return:
        """
        term = self.termination(scenario)
        if not term.term_node.entity_type == 'process':
            raise DependentFragment('Child flows are set during traversal')

        if scenario is None and self.reference_entity is None:
            # this counts as observing the reference flow
            if self.observed_ev == 0:
                self.observed_ev = self.cached_ev

        children = defaultdict(list)  # need to allow for differently-terminated child flows -- distinguish by term.id

        for k in self.child_flows:
            key = (k.flow.external_ref, k.direction)
            children[key].append(k)
        if len(children) == 0:
            return

        for x in term.term_node.inventory(ref_flow=term.term_flow, direction=term.direction):
            if x.value is None:
                self.dbg_print('skipping None-valued exchange: %s' % x)
                continue

            key = (x.flow.external_ref, x.direction)
            if key in children:
                try:
                    if len(children[key]) > 1:
                        child = next(c for c in children[key] if c.termination(scenario).id == x.termination)
                    else:
                        child = next(c for c in children[key])
                except StopIteration:
                    continue

                self.dbg_print('setting %s [%10.3g]' % (child, x.value))
                if scenario is None:
                    if reset_cache:
                        child.reset_cache()
                        child.cached_ev = x.value
                    else:
                        child.observed_ev = x.value
                else:
                    child.set_exchange_value(scenario, x.value)

    def _node_weight(self, magnitude, scenario):
        term = self.termination(scenario)
        '.'.'.
        if self.reference_entity is None and term.is_fg:
            return magnitude / self.exchange_value(scenario, observed=observed)
        '.'.'.
        if term is None or term.is_null:
            return magnitude

        else:
            return magnitude * term.node_weight_multiplier

    def _cache_balance_ev(self, _balance, scenario, observed):
        """
        TL;DR: need to stop caching balance flows, including subfragment traversal results, and move towards using
        live traversals (i.e. lists of FragmentFlows) for EVERYTHING from show_tree() to reports. For the time
        being, the cached values will report whatever was the LAST cached value-- so if a fragment is un-traversed
        in a certain scenario, particularly if the scenario affects a sub-fragment and not the local fragment,
        it will retain a false cache value.

        Still not totally clear on live traversals-- but maybe we simply SHOULDN'T cache if match is None.  But really
        we should move away from querying cached exchange values.  And we definitely shouldn't serialize exchange values
        for un-observable fragments.

        I think we should actually raise an exception when exchange value is queried for non-None scenario on a non-
        observable flow, requiring client code to use the FragmentFlow.

        BIG FAT BUG: evs can be modified by scenarios not defined locally in the current fragment.  Ergo, checking to
        see if the fragment's ev dict has the given scenario is not sufficient- we should not be setting the
        'observed ev' when any scenario is in effect. the whole scenario tuple needs to be used. this is a cheap dict,
        after all.  For balancing + fragment child flows only.  so this needs to be thought through somewhat.
        ans- no it doesn't! if they are balance / fffc flows, then their ev is never used! the ev dict is only for
        recordkeeping!  except set_exchange_value is limited to one scenario. so- don't use it.
        :param _balance:
        :param scenario:
        :return:
        """
        if scenario is None:
            if observed:
                self._exchange_values[1] = _balance
            else:
                self._exchange_values[0] = _balance
        else:
            match = self._match_scenario_ev(scenario)
            if match is not None:
                self._exchange_values[match] = _balance
    '''
    def nodes(self, scenario=None, descend=True):
        """
        Report proximal terminal nodes for the fragment (recurse until a nondescend is reached)
        :param scenario: [None]
        :param descend: [True] if False, yield subfragments as nodes
        :return: generator of terminal nodes
        """
        term = self.termination(scenario)
        yds = set()
        if term.is_process or term.is_context:
            if term.term_node not in yds:
                yield term.term_node
                yds.add(term.term_node)
        elif term.is_subfrag:
            if term.descend and descend:
                for n in term.term_node.nodes(scenario, descend=descend):
                    if n not in yds:
                        yield n
                        yds.add(n)
            else:
                yield term.term_node
            # foreground, null: do nothing
        for c in self.child_flows:
            for n in c.nodes(scenario, descend=descend):
                if n not in yds:
                    yield n
                    yds.add(n)

    def tree(self):
        """
        This is real simple- just a recursive enumeration of child flows, depth first

        :return:
        """
        yield self
        for c in self.child_flows:
            for b in c.tree():
                yield b

    def fragment_lcia(self, quantity_ref, scenario=None, observed=True, **kwargs):
        """
        Fragments don't have access to a qdb, so this piggybacks on the quantity_ref.
        note: refresh is no longer supported during traversal
        :param quantity_ref:
        :param scenario:
        :param observed: [True] whether to limit the computation to observed flows
        :param kwargs: ultimately passed down to LCIA computation routine
        :return:
        """
        fragmentflows = self.traverse(scenario=scenario, observed=observed)
        return frag_flow_lcia(fragmentflows, quantity_ref, scenario=scenario, **kwargs)

    def activity(self, scenario=None, observed=True):
        """
        Reports a list of node activities of direct descendants only
        :param scenario:
        :param observed:
        :return:
        """
        top = self.top()

        ffs = top.traverse(scenario=scenario, observed=observed)

        act = [k for k in ffs if k.fragment.top() is top]
        return act

    def inventory(self, scenario=None, scale=1.0, observed=False):
        """
        Converts unit inventory into a set of exchanges for easy display
        :param scenario:
        :param scale:
        :param observed:
        :return:
        """
        ios, _ = self.unit_inventory(scenario=scenario, observed=observed)
        return ios_exchanges(ios, ref=self)

    def exchanges(self, scenario=None):
        """
        Generator for query compatibility with processes
        :param scenario:
        :return:
        """
        for x in self.inventory(scenario=scenario):
            yield x

    def unit_inventory(self, scenario=None, observed=False, frags_seen=None):
        """
        Traverses the fragment containing self, and returns a set of FragmentFlows indicating the net input/output
         with respect to a *unit node weight of the reference fragment*.

        Within the set of fragment flows:
         * all will have null terminations
         * every flow appears with only one direction
         * the fragment's reference flow will appear with a direction relative to the fragment.

        Created to encapsulate a traversal problem.

        :param scenario:
        :param observed:
        :param frags_seen: to prevent recursive loops
        :return: list of io flows,
        """
        top = self.top()

        if frags_seen:
            frags_seen = set(frags_seen)  # reset to allow reentry

        ffs = top.traverse(scenario, observed=observed, frags_seen=frags_seen)

        ios, internal = group_ios(self, ffs)

        return ios, internal

    def cutoffs(self, scenario=None, observed=False):
        return self.inventory(scenario=scenario, observed=observed)

    def _deprecated_cutoffs(self, scenario=None, observed=False, aggregate=True):
        """
        Return a comprehensive list of cut-offs from a traversal result. Include implicit cutoffs from background
         computations.
        :param scenario:
        :param observed:
        :param aggregate: [True] if True, group cutoffs from different nodes together by flow.  If False, report each
        cutoff from a distinct node distinctly.
        :return:
        """
        ffs = self.traverse(scenario, observed=observed)
        cos = []
        for ff in ffs:
            if ff.term.is_null:
                cos.append(ff)
            else:
                if ff.fragment.is_background:
                    '''extend ff with background node cut-off flows.
                    Need to think about this for a minute because self.is_background could be terminated to either
                    a process or a fragment.  If it's a process, then for fragment LCIA we will be computing bg_lcia,
                    so assuming a CatalogRef with background access.
                    '''
                    ref = ff.term.term_node
                    cos.extend([FragmentFlow.cutoff(ff.fragment, i.flow, i.direction, i.value * ff.node_weight)
                                for i in ref.lci(ref_flow=ff.term.term_flow.external_ref)
                                if i.type in ('cutoff', 'context')])
                elif ff.term.is_process:
                    # TODO: add in cutoffs from unobserved exchanges
                    pass

        if aggregate:
            cos, _ = group_ios(self, cos, include_ref_flow=False)

        return sorted([ExchangeValue(f.fragment, f.fragment.flow, f.fragment.direction, value=f.magnitude)
                       for f in cos], key=lambda x: (x.direction == 'Input', x.flow.context,
                                                     x.flow['Name'], x.value), reverse=True)

    def traverse(self, scenario=None, observed=False, frags_seen=None):
        if isinstance(scenario, set):
            scenarios = set(scenario)
        elif isinstance(scenario, tuple) or isinstance(scenario, list):
            scenarios = set(scenario)
        elif scenario is None:
            if observed:
                scenarios = {1}
            else:
                scenarios = None
        else:
            scenarios = {scenario}
        ffs, _ = self._traverse_node(1.0, scenarios, frags_seen=frags_seen)
        return ffs

    def _traverse_fg_node(self, ff, scenarios, frags_seen):
        """
        Handle foreground nodes and processes--> these can be quantity-conserving, but except for
        balancing flows the flow magnitudes are determined at the time of construction (or scenario specification).

        Balancing flow exchange values are always determined with respect to a unit activity of the terminal node.

        This is messy so it deserves some notes.
        the fragment's exchange value specifies the scaling factor for the terminal node, EXCEPT if the
        fragment is a reference fragment (no parent) AND the terminal node is in the foreground.  In this case
        ONLY, the exchange value functions as an inbound exchange value, and the node weight should be 1.0.
        The prototypical example of this is a fragment for cultivation of 1 ha of corn, with the reference
        flow being (e.g.) 9300 kg of corn.  The reference fragment's exchange value is 9300 kg; the reference
         node's node weight is 1.0

        If the reference node has a balancing flow (say, we want to balance carbon content), then the stock
        value is the reference flow converted to the conservation quantity, e.g. 9300 * 0.43 = 3999 kg C, sign
        negative since it's going out (note that the reference fragment's direction is 'Input' in this case
        because direction is always interpreted relative to the parent).

        So then we traverse the child flows, let's say none of them have kg C characterization, and so our stock
        remains -3999 kg. WHen we hit the balancing fragment "atmospheric carbon in", we catch the FoundBalanceFlow
        and come back to it.

        When we come back, we re-negate the stock to +3999 and pass that as _balance to the balancing flow, which
        becomnes that flow's exchange value (again w.r.t. this node's unit node weight).

        IF the terminal node is a process, or if the node is an interior (non-reference) fragment, it's much easier.
        The stock is simply the process's inbound exchange value (with respect to a unit activity level), or if
        it's a foreground node then the stock is simply 1, and the node_weight already accounts for the exchange
        value and scales the balancing flow correctly.

        Were we to do this non-'live' or with some kind of stack, we could conceivably balance multiple quantities with
        additional fragment flows, but I'm pretty sure the same effect can be achieved by nesting conserving fragments.
        This also requires the modeler to specify a resolution order and cuts the need for elaborate error checking.

        :param ff: a FragmentFlow containing the foreground termination to recurse into
        :param scenarios:
        :param frags_seen:
        :return: a list of FragmentFlows in the order encountered, with input ff in position 0
        """
        term = ff.term
        node_weight = ff.node_weight
        ffs = [ff]
        stock_inflow = stock_outflow = 0.0  # keep track of total inflows to detect+quash near-zero (floating-point-tolerance) balances

        if term.is_fg or not term.valid:
            if self.reference_entity is None:
                # inbound exchange value w.r.t. term node's unit magnitude
                stock = self.exchange_value(scenarios)
            else:
                stock = 1.0  # balance measurement w.r.t. term node's unit magnitude
        else:
            stock = term.inbound_exchange_value  # balance measurement w.r.t. term node's unit magnitude
        bal_f = None
        if self.is_conserved_parent:
            stock *= self.balance_magnitude
            if self.direction == 'Input':  # convention: inputs to self are positive
                #  direction w.r.t. parent so self.direction == 'Input' is an input to parent = output from node
                stock *= -1
            self.dbg_print('%g inbound-balance' % stock, level=2)

        if stock > 0:
            stock_inflow += stock
        else:
            stock_outflow -= stock
        # TODO: Handle auto-consumption!  test child flows for flow identity and null term; cumulate; scale node_weight

        for f in self.child_flows:
            try:  # now that we are storing _balance_child we can just skip it instead of try-catch. but whatever.
                # traverse child, collecting conserved value if applicable
                child_ff, cons = f._traverse_node(node_weight, scenarios,
                                                  frags_seen=frags_seen, conserved_qty=self.conserved_quantity)
                if cons is None:
                    self.dbg_print('-- returned cons_value', level=3)
                else:
                    self.dbg_print('%g returned cons_value' % cons, level=2)
                    stock += cons
                    if cons > 0:
                        stock_inflow += cons
                    else:
                        stock_outflow -= cons
            except FoundBalanceFlow:
                self.dbg_print('%g bal magnitude on %.3s' % (stock, f.uuid), level=3)
                bal_f = f
                child_ff = []

            ffs.extend(child_ff)

        stock_max = max([abs(stock_inflow), abs(stock_outflow)])

        if bal_f is not None:
            # balance reports net inflows; positive value is more coming in than out
            # if balance flow is an input, its exchange must be the negative of the balance
            # if it is an output, its exchange must equal the balance
            if stock != 0 and (abs(stock) / stock_max < 1e-10):
                self.dbg_print('Quashing <1e-10 balance flow (%g vs %g)' % (stock, stock_inflow), level=1)
                stock = 0.0
            if bal_f.direction == 'Input':
                stock *= -1
                self.dbg_print('%.3s Input: negating balance value' % bal_f.uuid)
            else:
                self.dbg_print('%.3s Output: maintaining balance value' % bal_f.uuid)
            self.dbg_print('%g balance value passed to %.3s' % (stock, bal_f.uuid))
            bal_ff, _ = bal_f._traverse_node(node_weight, scenarios,
                                             frags_seen=set(frags_seen), conserved_qty=None, _balance=stock)
            ffs.extend(bal_ff)

        return ffs

    def _traverse_subfragment(self, ff, scenarios, frags_seen):
        """
        handle sub-fragments, including background flows--
        for sub-fragments, the flow magnitudes are determined at the time of traversal and must be pushed out to
         child flows
        for LOCAL background flows, the background ff should replace the current ff, maintaining self as fragment

        subfragment activity level is determined as follows:
         - if the subfragment is a background fragment, it MUST have a unity inbound_exchange_value; this is enforced:
           - for background processes, because FlowTermination._unobserved_exchanges() uses term_node.lci(ref_flow)
           - for background fragments, in the yet-to-be-implemented bg_lcia method  (part of the foreground interface??)
           in any case, the background term is swapped into the foreground node.

         - otherwise, the subfragment inventory is taken and grouped, and the matching flow is found, and the magnitude
           of the matching flow is used to normalize the downstream node weight.

         - then the inventory of the subfragment is used to apply exchange values to child fragments, and traversal
           recursion continues.


        :param ff: a FragmentFlow containing the non-fg subfragment termination to recurse into
        :param scenarios:
        :param frags_seen:
        :return:
        """
        '''
        '''

        term = ff.term
        if 0:  #  term.term_is_bg: this is deprecated
            pass
            '''
            if term.term_flow == term.term_node.flow:
                # collapse trivial bg terminations into the parent fragment flow
                bg_ff, _ = term.term_node._traverse_node(ff.node_weight, scenario, observed=observed)
                assert len(bg_ff) == 1, (self.uuid, term.term_node.external_ref)
                bg_ff[0].fragment = self
                return bg_ff
            '''

        # traverse the subfragment, match the driven flow, compute downstream node weight and normalized inventory
        try:
            ffs, unit_inv, downstream_nw = _do_subfragment_traversal(ff, scenarios, frags_seen)
        except ZeroInboundExchange:
            self.dbg_print('subfragment divide by zero', 1)
            return [ff]

        # next we traverse our own child flows, determining the exchange values from the normalized unit inventory
        for f in self.child_flows:
            self.dbg_print('Handling child flow %s' % f, 4)
            ev = 0.0
            try:
                m = next(j for j in unit_inv if j.fragment.flow == f.flow)
                if m.fragment.direction == f.direction:
                    self.dbg_print('  ev += %g' % m.magnitude, 4)
                    ev += m.magnitude
                else:
                    self.dbg_print('  ev -= %g' % m.magnitude, 4)
                    ev -= m.magnitude
                unit_inv.remove(m)
            except StopIteration:
                self.dbg_print('  no driving flows found')
                continue

            self.dbg_print('traversing with ev = %g' % ev, 4)
            child_ff, _ = f._traverse_node(downstream_nw, scenarios,
                                           frags_seen=frags_seen, _balance=ev)
            ffs.extend(child_ff)

        # remaining un-accounted io flows are getting appended, so do scale
        for x in unit_inv:
            x.scale(downstream_nw)
        ffs.extend(list(unit_inv))

        return ffs

    def _traverse_node(self, upstream_nw, scenarios,
                       frags_seen=None, conserved_qty=None, _balance=None):

        """
        If the node has a non-null termination, use that; follow child flows.

        If the node's termination is null- then look for matching background fragments. If one is found, adopt its
        termination, and return.

        else: assume it is a null foreground node; follow child flows

        :param upstream_nw: upstream node weight
        :param scenarios: set of scenario values
        #:param observed: whether to use observed or cached evs (overridden by scenario specification)
        :param frags_seen: carried along to catch recursion loops
        :param conserved_qty: in case the parent node is a conservation node
        :param _balance: used when flow magnitude is determined during traversal, i.e. for balance flows and
        children of fragment nodes
        :return: 2-tuple: ffs, conserved_val
          ffs = an array of FragmentFlow records reporting the traversal, beginning with self
          conserved_val = the magnitude of the flow with respect to the conserved quantity, if applicable (or None)
        """

        # first check for cycles
        if frags_seen is None:
            frags_seen = set()

        if self.reference_entity is None:
            if self.uuid in frags_seen:
                # this should really get resolved into a loop-closing algorithm
                raise InvalidParentChild('Frag %s seeing self\n %s' % (self.uuid, '; '.join(frags_seen)))
            frags_seen.add(self.uuid)

        if _balance is None:
            _scen_ev = self._match_scenario_ev(scenarios)
            ev = self.exchange_value(_scen_ev)
        else:
            _scen_ev = None
            self.dbg_print('%g balance' % _balance, level=2)
            ev = _balance
            '''
            if self._check_observability(scenario):
                self._cache_balance_ev(_balance, scenario, observed)
            '''

        magnitude = upstream_nw * ev
        _scen_term = self._match_scenario_term(scenarios)
        term = self._terminations[_scen_term]

        if self.reference_entity is None:
            node_weight = upstream_nw
            if magnitude == 0:
                self.dbg_print('Unobserved reference fragment')
                node_weight = 0
        else:
            node_weight = magnitude

        node_weight *= term.node_weight_multiplier

        self.dbg_print('magnitude: %g node_weight: %g' % (magnitude, node_weight))

        conserved_val = None
        if conserved_qty is not None:
            if self.is_balance:
                self.dbg_print('Found balance flow')
                raise FoundBalanceFlow  # to be caught
            cf = conserved_qty.cf(self.flow)
            self.dbg_print('consrv cf %g for qty %s' % (cf, conserved_qty), level=3)
            conserved_val = ev * cf
            if conserved_val == 0:
                conserved = False
            else:
                conserved = True
                if self.direction == 'Output':  # convention: inputs to parent are positive
                    conserved_val *= -1
                self.dbg_print('conserved_val %g' % conserved_val, level=2)
        elif self.is_balance:
            # traversing balance flow after FoundBalanceFlow exception
            conserved = True
        else:
            conserved = self.conserved

        # print('%6f %6f %s' % (magnitude, node_weight, self))
        # this is the only place a FragmentFlow is created
        # TODO: figure out how to cache + propagate matched scenarios ... in progress
        ff = FragmentFlow(self, magnitude, node_weight, term, conserved, match_ev=_scen_ev, match_term=_scen_term)

        '''
        now looking forward: is our termination a cutoff, background, foreground or subfragment?
        '''
        if magnitude == 0:
            # no flow to follow
            self.dbg_print('zero magnitude')
            return [ff], conserved_val
        elif term.is_null or term.is_context:
            # cutoff /context and background end traversal
            self.dbg_print('cutoff or bg')
            return [ff], conserved_val

        if term.is_fg or term.is_process or not term.valid:
            self.dbg_print('fg')
            ffs = self._traverse_fg_node(ff, scenarios, frags_seen)

        else:
            self.dbg_print('subfrag')
            ffs = self._traverse_subfragment(ff, scenarios, frags_seen)

        return ffs, conserved_val


def _do_subfragment_traversal(ff, scenarios, frags_seen):
    """
    This turns out to be surprisingly complicated. So we now have:
     - LcFragment._traverse_node <-- which is called recursively
      + scenario matching + finds ev and term
      - selects handler based on term type:
       - LcFragment._subfragment_traversal
       |- invokes (static) _do_subfragment_traversal (YOU ARE HERE)
       ||- calls [internally recursive] term_node.unit_inventory, which is just a wrapper for
       || - (static) group_ios
       ||  + reference flow and autoconsumption handling
       || /
       ||/
       |+ reference flow matching and normalizing
       + child flow matching and further recursion --> into LcFragment._traverse_node
      /
     /
     ffs, conserved_val


     - (static) group_ios
     - nested inside LcFragment.unit_inventory, which is really just a wrapper
     - called from
     - called from

    :param ff: The FragmentFlow whose subfragment is being traversed
    :param scenarios: to pass to subfragment
    :return: ffs [subfragment traversal appended], unit_inv [with reference flow removed], downstream node weight
    """
    term = ff.term  # note that we ignore term.direction in subfragment traversal
    node_weight = ff.node_weight
    self = ff.fragment

    unit_inv, subfrags = term.term_node.unit_inventory(scenario=scenarios, frags_seen=frags_seen)

    # find the inventory flow that matches us
    # use term_flow over term_node.flow because that allows client code to specify inverse traversal knowing
    #  only the sought flow.
    # unit_inventory guarantees that there is exactly one of these flows (except in the case of cumulating flows!
    # see group_ios)
    try:
        match = next(k for k in unit_inv if k.fragment.flow == term.term_flow)
    except StopIteration:
        print('Flow mismatch Traversing:\n%s' % self)
        print('Term flow: %s' % term.term_flow.link)
        print(term.serialize())
        for k in unit_inv:
            print('%s' % k.fragment.flow.link)
        raise MissingFlow('Term flow: %s' % term.term_flow.link)
    self.dbg_print('matched flow %s' % match.fragment.flow.link)

    unit_inv.remove(match)

    in_ex = match.magnitude  # this is the inbound exchange value for the driven fragment
    if in_ex == 0:
        # this indicates a non-consumptive pass-thru fragment.
        print('Frag %.5s: Zero inbound exchange' % self.uuid)
        raise ZeroInboundExchange
    if match.fragment.direction == self.direction:  # match direction is w.r.t. subfragment
        # self is driving subfragment in reverse
        self.dbg_print('reverse-driven subfragment %.3s' % match.fragment.uuid)
        in_ex *= -1

    # node weight for the driven [downstream] fragment
    downstream_nw = node_weight / in_ex

    '''
    # then we add the results of the subfragment, either in aggregated or disaggregated form
    if term.descend:
        # if appending, we are traversing in situ, so do scale
        self.dbg_print('descending', level=0)
        for i in subfrags:
            i.scale(downstream_nw)
        ffs = [ff]
        ffs.extend(subfrags)
    else:
        # if aggregating, we are only setting unit scores- so don't scale
        self.dbg_print('aggregating', level=0)
        ff.aggregate_subfragments(subfrags, scenarios=scenarios)  # include params to reproduce
        ff.node_weight = downstream_nw  # NOTE: this may be problematic; undone in lca_disclosures
        ffs = [ff]
    '''
    # now, we abolish descend as a traversal parameter and make it only an LCIA parameter
    # therefore, we retain subfragments always, we just have to decide how to scale them
    self.dbg_print('%d subfrags resulting from this traversal' % len(subfrags), 1)
    ff.aggregate_subfragments(subfrags, scenarios=scenarios)
    ff.node_weight = downstream_nw
    ffs = [ff]

    return ffs, unit_inv, downstream_nw
