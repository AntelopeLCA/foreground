from antelope import comp_dir, ExchangeRef

from .terminations import FlowTermination, UnCachedScore, UnresolvedAnchor
from .models import DescendSpec
from antelope_core.lcia_results import LciaResult, DetailedLciaResult, SummaryLciaResult

from collections import defaultdict
import uuid
import logging


class FragmentInventoryDeprecated(Exception):
    """
    The "inventory" term for fragmnts is deprecated.  "unit_inventory" is now "unit_flows" and "inventory"
    is what it has always been: "cutoffs".  And the old "cutoffs" is gone because it literally never worked.
    """
    pass


class CumulatingFlows(Exception):
    """
    when a fragment includes multiple instances of the reference flow having consistent (i.e. not complementary)
    directions. Not handled in subfragment traversal bc no valid test case
    """
    pass


class FragmentFlow(object):
    """
    A FragmentFlow is a an immutable record of a traversal query. essentially an enhanced NodeCache record which
    can be easily serialized to an antelope fragmentflow record.

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

    """
    '''
    @classmethod
    def from_antelope_v1(cls, j, query):
        """
        Need to:
         * create a termination
         * create a fragment ref
         * extract node weight
         * extract magnitude
         * extract is_conserved
        :param j: JSON-formatted fragmentflow, from a v1 .NET antelope instance.  Must be modified to include StageName
         instead of fragmentStageID
        :param query: an antelope v1 catalog query
        :return:
        """
        return cls(frag, magnitude, nw, term, conserved)

    @classmethod
    def ref_flow(cls, parent, use_ev):
        """

        :param parent:
        :param use_ev: required to create reference flows from fragment refs
        :return:
        """
        fragment = GhostFragment(parent, parent.flow, comp_dir(parent.direction))
        term = FlowTermination.null(fragment)
        return cls(fragment, use_ev, 1.0, term,
                   parent.is_conserved_parent)
    '''

    @classmethod
    def cutoff(cls, parent, flow, direction, magnitude, is_conserved=False):
        fragment = GhostFragment(parent, flow, direction)
        term = FlowTermination.null(fragment)
        return cls(fragment, magnitude, magnitude, term, is_conserved)

    def __init__(self, fragment, magnitude, node_weight, term, is_conserved, match_ev=None, match_term=None,
                 flow_conversion=1.0):
        """

        :param fragment:
        :param magnitude:
        :param node_weight: flow (or balance) magnitude * flow conversion / anchor inflow magnitude
        :param term:
        :param is_conserved:
        :param match_ev:
        :param match_term:
        :param flow_conversion: [1.0] stored in the FragmentFlow for information purposes only. Negative value
         indicates a direction change at the anchor (driven anchor)
        """
        # TODO: figure out how to cache + propagate scenario applications through aggregation ops
        self.fragment = fragment
        self.magnitude = magnitude
        self.node_weight = node_weight
        self.flow_conversion = flow_conversion
        self.term = term
        self.is_conserved = is_conserved
        self._subfrags_params = ()
        self.match_scenarios = (match_ev, match_term)
        self._superfrag = None
        self.uuid = str(uuid.uuid4())

    @property
    def superfragment(self):
        return self._superfrag

    @property
    def subfragments(self):
        if self.term.is_subfrag:  # and (self.term.descend is False):
            try:
                return self._subfrags_params[0]
            except IndexError:
                return []
        return []

    @property
    def subfragment_scenarios(self):
        try:
            return self._subfrags_params[1]
        except IndexError:
            return None

    def aggregate_subfragments(self, subfrags, scenarios=None):
        """
        We need to save the full traversal specification (
        :param subfrags:
        :param scenarios:
        :return:
        """
        for f in subfrags:
            f._superfrag = self
        self._subfrags_params = (subfrags, scenarios)

    def scale(self, x):
        self.node_weight *= x
        self.magnitude *= x

    @property
    def name(self):
        return self.term.name

    def screen_name(self, length=80):
        """
        auto-compact for display

        :return:
        """
        name = self.name
        if len(name) > length:
            name = name[:(length - 18)] + '....' + name[-14:]
        return name

    def __str__(self):
        return '%.5s  %10.3g [%6s] %s %s' % (self.fragment.uuid, self.magnitude, self.fragment.direction,
                                             self.term, self.name)

    def __add__(self, other):
        if isinstance(other, FragmentFlow):
            if other.fragment.uuid != self.fragment.uuid:
                raise ValueError('Fragment flows do not belong to the same fragment')
            mag = other.magnitude
            nw = other.node_weight
            if not self.term == other.term:
                raise ValueError('These fragment flows are differently terminated')

            if mag * self.node_weight != (self.magnitude * nw):  # formally if m*N/M*n != 1.0:
                raise ValueError('These fragment flows cannot be combined because their implicit evs do not match')
            conserved = self.is_conserved and other.is_conserved

            mod_mag = mag * other.flow_conversion / self.flow_conversion
            """
        elif isinstance(other, DetailedLciaResult):
            print('DEPRECATED: adding FragmentFlow to DetailedLciaResult')
            if other.exchange.process is not self.fragment:
                raise ValueError('FragmentFlow and DetailedLciaResult do not belong to the same fragment')
            nw = other.exchange.value
            mag = nw
            conserved = False
        elif isinstance(other, SummaryLciaResult):
            print('DEPRECATED: adding FragmentFlow to SummaryLciaResult')
            if other.entity is not self.fragment:
                raise ValueError('FragmentFlow and SummaryLciaResult do not belong to the same fragment')
            nw = other.node_weight
            mag = nw
            conserved = False
            """
        else:
            raise TypeError("Don't know how to add type %s to FragmentFlow\n %s\n to %s" % (type(other), other, self))
        # don't check unit scores-- ?????
        new = FragmentFlow(self.fragment, self.magnitude + mod_mag, self.node_weight + nw,
                           self.term, conserved, flow_conversion=self.flow_conversion)
        return new

    def get(self, item, default=None):
        return self.fragment.get(item, default=default)

    def __getitem__(self, item):
        return self.fragment.__getitem__(item)

    def __eq__(self, other):
        """
        FragmentFlows are equal if they have the same fragment and termination.  Formerly magnitude too but why?
        answer why: because if not, then two traversals from two different scenarios can appear equal
        answer why not: because of LciaResult issues, presumably- let's put this on the list for later
        :param other:
        :return:
        """
        if not isinstance(other, FragmentFlow):
            return False
        return self.fragment == other.fragment and self.term == other.term  # and self.node_weight == other.node_weight

    def __hash__(self):
        return hash(self.fragment)

    @property
    def ref_unit(self):
        return self.fragment.flow.unit


def group_ios(parent, ffs, include_ref_flow=True, passthru_threshold=0.45):
    """
    Utility function for dealing with a traversal result (list of FragmentFlows)
    Creates a list of cutoff flows from the inputs and outputs from a fragment traversal.

    Returns two lists of FragmentFlows: external (inputs+outputs) and internal to the traversal.

    Pass-Thru Flows and Autoconsumption

    There is a challenge in dealing a fragment whose inventory contains the fragment's own reference flow.  The two
    broad interpretations of this are that the substance is "passing through" the fragment, or that the fragment
    induces further consumption of its reference flow or demand for its own service.  Both approaches are logical in
    different circumstances, and it is difficult to tell the difference in certain cases.

    There are eight cases: whether the flow directions are complementary or cumulative, whether the flow grows or
    shrinks, whether the reference direction is input or output.  Pictorially, with <== and <-- indicating larger and
    smaller flows respectively; * representing the reference fragment; --: representing the child flows

    A.1.a  <== *--: <--   augmentation?             B.1.  ==> *--: <--  cumulating sink; NONSENSICAL
        b  <-= *--  <--   autoconsumption?

    A.2.   <-- *--: <==   depletion / yield loss    B.2.  --> *--: <==  cumulating sink; NONSENSICAL
                          induced load NONSENSICAL

    A.3.a  ==> *--: -->   depletion / yield loss?   B.3.  <== *--: -->  cumulating source; NONSENSICAL
        b  -=> *--  -->   induced self-load? (probably nonsensical)

    A.4.   --> *--: ==>   augmentation              B.4.  <-- *--: ==>  cumulating source; NONSENSICAL
                          autoconsumption NONSENSICAL

    In all the (B) cases where the two flows are oppositely directed, the driven fragment multiplies its own effect, and
    these fragment designs are considered nonsensical and are not allowed.

    In cases A.2 and A.4, autoconsumption is nonsensical because it would require the induced amount to be modeled as
    the reference flow, but the induced amount cannot be induced by itself.  So these are automatically interpreted as
    pass-through (i.e. A.2 is depletion of a passed-through flow; A.4 is accumulation of a passed-through flow).

    In cases A.1 and A.3 however, either could apply:

    A.1.a A component is supplied after being further assembled
    A.1.b grid power / pipeline service consumes its own output in delivering its service

    A.3.a A recycling stream is purified of contaminants
    A.3.b A treatment process generates some of its own waste for treatment (??) maybe nonsensical but we allow it

    In these cases, helpless to divine the modeler's intent, we apply a threshold.  If the induced amount is below this
    threshold as a fraction of the reference flow, it will be taken as an autoconsumption process-- the induced flow
    will be subsumed into the reference flow, reducing its magnitude.

    If the induced amount exceeds this threshold, the process will be taken to be an augmentation / depletion pass-
    through process.  The threshold is set to 0.33, just because it seems safe to assume that an induced load will not
    exceed 33% of the direct load, or that a process will not augment or deplete its own flow by 3x.

    As a reminder, if you need to model such a process, it is easy to do- just give the input and output distinct flows!

    :param parent: the node generating the cutoffs
    :param ffs: a list of fragment flows resulting from a traversal of the parent
    :param include_ref_flow: [True] whether to include the reference fragment and adjust for autoconsumption
    :param passthru_threshold: [0.33] smaller than this is treated as autoconsumption / induced load
    :return: [list of grouped IO flows], [list of internal non-null flows]
    """
    out = defaultdict(float)  # accumulates net total
    pos_mag = defaultdict(float)  # accumulates +ve
    neg_mag = defaultdict(float) # accumulates -ve
    dirs = dict()
    # cons = dict()
    internal = []
    external = []
    for ff in ffs:
        if ff.term.is_null:
            # accumulate IO flows according to the first seen direction
            if ff.fragment.flow not in dirs:
                dirs[ff.fragment.flow] = ff.fragment.direction
            # and correct the signs of subsequent flows
            if ff.fragment.direction == dirs[ff.fragment.flow]:
                magnitude = ff.magnitude
            else:
                magnitude = -ff.magnitude

            ''' # ditto conservation status  # but this doesn't work
            if ff.fragment.flow not in cons:
                cons[ff.fragment.flow] = ff.is_conserved
            else:
                if ff.is_conserved ^ cons[ff.fragment.flow]:
                    print('** Surprise! conservation status not shared among matching flows %s' % ff.fragment.uuid)
            '''

            out[ff.fragment.flow] += magnitude
            if magnitude > 0:  # separate test from above because we are ignoring relative-directions
                pos_mag[ff.fragment.flow] += magnitude  # positive
            else:
                neg_mag[ff.fragment.flow] -= magnitude  # positive
        else:
            internal.append(ff)

    # now deal with reference flow-- trivial fragment should wind up with two equal-and-opposite [pass-through] flows
    ref_frag = parent.top()
    if include_ref_flow:
        # ref_cons = ref_frag.is_conserved_parent
        ref_mag = ffs[0].magnitude
        if ref_frag.flow in out:  # either pass through or autoconsumption
            ref_frag.dbg_print('either pass through or autoconsumption')
            val = out[ref_frag.flow]
            auto_dirn = dirs[ref_frag.flow]
            if val < 0:
                auto_dirn = comp_dir(auto_dirn)  # this is rare, but
            # else:
            #    auto_dirn = 'Input'
            """
            If the directions are cumulating, we raise an error- bad fragment design. 
            
            If directions are complementary [meaning equal since ref flow dirn is w.r.t. parent], this means the 
            reference outflow is an inventory inflow, or the reference inflow is an inventory outflow.
            
            We apply a threshold, where if the induced flow is below the threshold w.r.t. the ref flow, autoconsumption
            is applied.
            """
            if auto_dirn == ref_frag.direction:  # equality here means complementary flows - direction is w.r.t. parent
                # case A here
                if abs(val) < (passthru_threshold * ref_mag):
                    # A.1.b and A.3.b
                    ref_frag.dbg_print('autoconsumption %g %g' % (val, ref_mag))
                    # autoconsumption, the inventory flow is subsumed by the ref_flow; direction sense should reverse
                    if auto_dirn == 'Output':
                        out[ref_frag.flow] += ref_mag
                    else:
                        out[ref_frag.flow] -= ref_mag
                    if ref_mag > 0:
                        pos_mag[ref_frag.flow] += ref_mag
                    else:
                        neg_mag[ref_frag.flow] -= ref_mag

                else:
                    # A.1.a, A.3.a, A.2, A.4
                    ref_frag.dbg_print('pass thru no effect %g %g' % (val, ref_mag))
                    # pass-thru: pre-initialize external with the reference flow, having the opposite direction
                    external.append(FragmentFlow.cutoff(parent, ref_frag.flow, comp_dir(auto_dirn), ref_mag)) #,
                                                        #is_conserved=ref_cons))
            else:
                # all case B
                ref_frag.dbg_print('cumulation! %g %g' % (val, ref_mag))
                # cumulation: the directions are both the same... should they be accumulated?  not handled
                raise CumulatingFlows('%s' % parent)
                # external.append(FragmentFlow.cutoff(parent, ref_frag.flow, auto_dirn, ref_mag))
        else:
            ref_frag.dbg_print('uncomplicated ref flow')
            # no autoconsumption or pass-through, but we still want the ref flow to show up in the inventory
            external.append(FragmentFlow.cutoff(parent, ref_frag.flow, comp_dir(ref_frag.direction), ref_mag)) #,
                                                #is_conserved=ref_cons))

    for flow, value in out.items():
        direction = dirs[flow]
        abs_mag = max([pos_mag[flow], neg_mag[flow]])
        if value != 0:
            if abs_mag == 0:  # we'd hate to get a ZeroDivisionError-- but this should be impossible
                print('group_ios weird zero abs_mag %.5s (%s: %g, %g)' % (ref_frag.uuid, flow, value, abs_mag))
            elif abs(value) / abs_mag < 1e-12:
                # these have never been controversial-- stop cluttering the console
                # print('Quashing group_ios flow < 1e-12 magnitude (%s: %g, %g)' % (flow, value, abs_mag))
                ref_frag.dbg_print('Quashing balance flow < 1e-12 magnitude (%s: %g, %g)' % (flow, value, abs_mag))
                value = 0.0
        if value < 0:
            direction = comp_dir(direction)
        external.append(FragmentFlow.cutoff(parent, flow, direction, abs(value)))  # , is_conserved=cons[flow]))

    return external, internal


def ios_exchanges(ios, ref=None, scale=1.0):
    if ref is None:
        ref = ios[0].fragment
    frag_exchs = []
    for f in ios:
        if f.magnitude == 0:
            continue
        is_ref = (f.fragment.flow == ref.flow and f.fragment.direction == comp_dir(ref.direction))

        xv = ExchangeRef(ref, f.fragment.flow, f.fragment.direction, value=f.magnitude * scale, is_reference=is_ref)
        frag_exchs.append(xv)
    return sorted(frag_exchs, key=lambda x: (x.direction == 'Input', x.value), reverse=True)


def frag_flow_lcia(fragmentflows, quantity_ref, scenario=None, descend_all=None, descend_spec=None, **kwargs):
    """
    Recursive function to compute LCIA of a traversal record contained in a set of Fragment Flows.
    Note: refresh is no longer supported during traversal
    :param fragmentflows:
    :param quantity_ref:
    :param scenario: necessary if any remote traversals are required
    :param descend_all: if True or False, disregard frag-specific descend settings in favor of spec
    :param descend_spec: a DescendSpec object (overrides above)
    :return:
    """
    if descend_spec is None:
        descend_spec = DescendSpec(descend_all=descend_all)

    result = LciaResult(quantity_ref, scenario=str(scenario))
    # _first_ff = True  # I have no idea what problem this was meant to solve
    for ff in fragmentflows:
        # _recursive_remote = False
        if ff.term.is_null:
            continue

        node_weight = ff.node_weight
        if node_weight == 0:
            continue

        if ff.term.direction == ff.fragment.direction:
            # if the directions collide (rather than complement), the term is getting run in reverse
            node_weight *= -1

        # if we have subfragments, use them
        if len(ff.subfragments) == 0:  # always true for: contexts, processes, remote subfragments
            try:
                v = ff.term.score_cache(quantity=quantity_ref, **kwargs)

                # if we reach here, then we have successfully retrieved a cached unit score and we are done
                if not v.is_null:
                    result.add_summary(ff.uuid, ff, node_weight, v)

                # _first_ff = False
                continue

            except UnresolvedAnchor:
                result.add_missing(ff.uuid, ff.term.term_node, node_weight)
                # _first_ff = False
                continue

            except UnCachedScore:
                # a subfragment with no stored subfragments and no cached score: we gotta ask
                v = ff.term.term_node.fragment_lcia(quantity_ref, scenario=scenario)
                # _recursive_remote = True  # skip this noise

        else:
            v = frag_flow_lcia(ff.subfragments, quantity_ref, scenario=ff.subfragment_scenarios,
                               descend_spec=descend_spec, **kwargs)
            if v.is_null:
                continue

        # if we arrive here, we have a unit score from a subfragment

        if descend_spec.descend_ff(ff):
            if v.has_summaries:
                for k in v.keys():
                    c = v[k]
                    result.add_summary(k, c.entity, c.node_weight * node_weight, c.internal_result)
            else:
                result.add_summary(ff.uuid, ff, node_weight, v)
        else:
            result.add_summary(ff.uuid, ff, node_weight, v)

        # if _first_ff and _recursive_remote:
        #     if len(fragmentflows) > 1:
        #         logging.warning('Bailing out early despite %d un-handled fragment flows' % (len(fragmentflows)-1))
        #     return result  # bail out
        # _first_ff = False
    return result


class GhostFragment(object):
    """
    A GhostFragment is a non-actual fragment used for reporting and aggregating fragment inputs and outputs
      during traversal.
      We're doing some digging into this because the prior iteration created totally non-functional FragmentFlow models
    """
    def __init__(self, parent, flow, direction):
        self._parent = parent
        self.flow = flow
        self.direction = direction
        self.uuid = str(uuid.uuid4())

    @property
    def origin(self):
        return self.flow.origin

    @property
    def external_ref(self):
        return self.uuid

    @property
    def parent(self):
        return self._parent

    @property
    def reference_entity(self):
        return self._parent

    @property
    def is_reference(self):
        return self._parent is None

    @property
    def is_background(self):
        return False

    @property
    def is_balance(self):
        """
        no way to track this through aggregation (in the present architecture)
        :return:
        """
        return False

    @property
    def entity_type(self):
        return 'fragment'

    @property
    def dirn(self):
        return {
            'Input': '-<-',
            'Output': '=>='
        }[self.direction]

    def top(self):
        return self._parent.top()

    def __str__(self):
        re = self.reference_entity.uuid[:7]
        return '(%s) %s %.5s %s --:   [%s] %s' % (re, self.dirn, self.uuid, self.dirn,
                                                  self.flow.unit, self.flow['Name'])

    def __eq__(self, other):
        """
        the LcEntity equality test is no good for GhostFragments because they replicate the same parent flow.
        We should test if parent, flow, and direction are the same.
        :return:
        """
        if other is None:
            return False
        # if not isinstance(other, LcEntity):  # taking this out so that CatalogRefs and entities can be compared
        #     return False
        try:
            is_eq = (self.reference_entity == other.reference_entity
                     and self.flow == other.flow
                     and self.direction == other.direction)
        except AttributeError:
            is_eq = False
        return is_eq

    def get(self, item, default=None):
        try:
            return self.__getitem__(item)
        except KeyError:
            return default

    def __getitem__(self, item):
        if item == 'parent':
            if self._parent:
                return self._parent.external_ref
            else:
                return None
        try:
            return self.flow[item]
        except KeyError:
            if self._parent:
                return self._parent[item]
            raise
