"""
Flow Terminations are model-defined links between a particular flow and a process that terminates it.

They originated as part of LcFragments but in fact they are more general. A FlowTermination is actually the same
as a ProductFlow in lca-matrix, plus features to compute LCIA.  It should be easy to construct either one from the
other.
"""
import logging

from antelope import (BackgroundRequired, check_direction, comp_dir, QuantityRequired, MultipleReferences,
                      NoReference, ConversionReferenceMismatch, EntityNotFound, NoCatalog)

from antelope.models import DirectedFlow
from antelope_core.contexts import NullContext
from antelope_core.exchanges import ExchangeValue
from antelope_core.lcia_results import LciaResult
from antelope_core.implementations.quantity import do_lcia
from .lcia_dict import LciaResults
from .models import Anchor, EntityRef, UNRESOLVED_ANCHOR_TYPE


# from lcatools.catalog_ref import NoCatalog
# from lcatools.interact import parse_math


class MissingFlow(Exception):
    """
    Raised when a termination does not match with the specified term_flow
    """
    pass


class FlowConversionError(Exception):
    pass


class SubFragmentAggregation(Exception):
    pass


class UnresolvedAnchor(Exception):
    pass


class NonConfigurableInboundEV(Exception):
    """
    only foreground terminations may have their inbound exchange values explicitly specified (and this via reference
    flow observation, NOT through specifying it on the anchor)
    """
    pass


class UnCachedScore(Exception):
    """
    means that we have an LCIA-only node whose score has not been set for the requested LCIA method
    """
    pass


class TerminationFromJson(Exception):
    """
    Something failed in deserialization
    """
    pass


class MalformedParent(Exception):
    """
    parent's flow or direction is None
    """
    pass


class FlowTermination(object):

    _term = None
    _term_flow = None
    _direction = None
    _descend = True

    """
    these are stored by scenario in a dict on the mainland

    A fragment can have the following types of terminations:
     * None - the termination is null- the flow enters the foreground and becomes an i/o
     * parent - the fragment's termination is the fragment itself.  The fragment flow  enters a foreground node.
       The node can have children but only has LCIA impacts based on the terminating flow, which have to be looked up
       in the database. fg-terminated nodes don't have scenarios (e.g. the scenarios are in the exchange values).
       Note: term_flows can be different from parent flows, and unit conversions will occur normally (e.g. "sulfur
       content" converted to "kg SO2")
     * Process - the flow enters a process referenced by CatalogRef.  The node's LCIA impacts are fg_lcia. The
       node's children are the process's non-term intermediate exchanges. The node can also have other children.
       (created with terminate or term_from_exch)
     * Fragment - the flow enters a sub-fragment.  The sub-fragment must be traversable. The node's children are
       the fragment's non-term io flows. The node cannot have other children.  If the sub-fragment is background,
       then the background fragment flow supplants the foreground one during traversal.

    LCIA results are always cached in the terminations, and are not (by default) persistent across instantiations.
    """
    @classmethod
    def from_json(cls, fragment, fg, scenario, j):
        if len(j) == 0:
            return cls.null(fragment)
        origin = j.pop('source', None) or j.pop('origin')
        if origin == 'foreground':
            origin = fg.ref

        # handle term flow
        tf_ref = j.pop('termFlow', None)
        if tf_ref is None:
            term_flow = None  # if it is unspecified, let the best value be determined
        elif isinstance(tf_ref, dict):
            term_flow = fg.catalog_ref(tf_ref['origin'], tf_ref['externalId'], entity_type='flow')
        else:
            if origin == fg.ref:
                term_flow = fg[tf_ref]
            else:
                term_flow = fg.catalog_ref(origin, tf_ref, entity_type='flow')

        if 'context' in j:
            term_node = fg.tm[j['context']]
        else:
            try:
                external_ref = j['externalId']
            except KeyError:
                external_ref = j['entityId']
            # handle term_node
            if origin == fg.ref:
                term_node = fg[external_ref]
            else:
                term_node = fg.catalog_ref(origin, external_ref, entity_type=UNRESOLVED_ANCHOR_TYPE)  # need to lookup type

        direction = j.pop('direction', None)
        descend = j.pop('descend', True)
        try:
            term = cls(fragment, term_node, _direction=direction, term_flow=term_flow, descend=descend)
        except MultipleReferences:
            raise TerminationFromJson('term_flow missing and ambiguous: %s (%s)' % (fragment.link, scenario))
        except FlowConversionError:
            t = term_flow or term_node
            raise TerminationFromJson('Flow Conversion Error %s =/= %s' % (fragment.link, t.link))
        if 'scoreCache' in j.keys():
            term._deserialize_score_cache(fg, j['scoreCache'], scenario)
        return term

    '''
    @classmethod
    def from_exchange_ref(cls, fragment, exchange_ref):
        return cls(fragment, exchange_ref.process_ref, direction=exchange_ref.direction,
                   term_flow=exchange_ref.exchange.flow, inbound_ev=exchange_ref.exchange.value)

    @classmethod
    def from_term(cls, fragment, term):
        return cls(fragment, term.term_node, direction=term.direction, term_flow=term.term_flow,
                   descend=term.descend, inbound_ev=term.inbound_exchange_value)
    '''

    @classmethod
    def null(cls, fragment):
        return cls(fragment, None)

    def __init__(self, fragment, entity, _direction=None, term_flow=None, descend=True, inbound_ev=None):
        """
        reference can be None, an entity or a catalog_ref.  It only must have origin, external_ref, and entity_type.
        To use an exchange, use FlowTermination.from_exchange()
         * None - to create a foreground IO / cutoff flow
         * fragment (same as parent) - to create a foreground node.  Must satisfy 'fragment is entity'
         * process or process ref - to link the fragment to a process inventory (uses self.is_background to determine
           foreground or background lookup)
         * context - to represent the fragment's flow (or term_flow, still supported) as emission
         * flow or flow ref - no longer supported.  Supply context instead.

        The term's direction is detected at the time of creation.

        :param fragment:
        :param entity:
        :param _direction: Should not be used externally- only if term is generated from_json
        :param term_flow: optional flow to match on termination inventory or LCIA.  If flow and term_flow have
        different reference quantities, quantity conversion is performed during traversal
        :param descend:
        :param inbound_ev: ignored; deprecated
        """
        if fragment.flow is None or fragment.direction is None:
            raise MalformedParent(fragment.link)
        self._parent = fragment
        if entity is not None:
            if entity.entity_type == 'flow':
                if term_flow is not None and term_flow != entity:
                    raise ValueError('Inconsistent flow and term_flow provided: %s' % entity)
                term_flow = entity
                entity = fragment  # foreground termination with flow conversion
                # raise TypeError('Can no longer terminate fragments with flows. Use context instead')
            elif entity.entity_type == 'exchange':
                term_flow = entity.flow
                _direction = entity.direction
                entity = entity.process
            elif entity.entity_type not in ('context', 'process', 'fragment', UNRESOLVED_ANCHOR_TYPE):
                raise TypeError('%s: term %s Inappropriate termination type: %s' % (fragment.link, entity.link,
                                                                                    entity.entity_type))

            # check for recursive loops
            if entity.entity_type == 'fragment' and entity is not fragment:
                if entity.top() is fragment.top():
                    # interior recursive loop can be resolved by leaving cut-off

                    print('-- setting cut-off flow to resolve recursive loop')
                    entity = None

        self._term = entity  # this must have origin, external_ref, and entity_type, and be operable (if ref)
        self._score_cache = LciaResults(fragment)

        self.term_flow = term_flow
        self.direction = _direction
        self.descend = descend

    @property
    def term_node(self):
        if self._term:
            if self._term.entity_type == UNRESOLVED_ANCHOR_TYPE:
                try:
                    self._term = self._term.resolve()
                except NoCatalog:
                    pass
        return self._term

    @property
    def term_flow(self):
        if self._term_flow is None:
            if self.is_process:
                raise AttributeError('[%s] term_flow was not specified for process term!' % self._parent.external_ref)
            if self.is_frag:
                return self.term_node.flow
            else:
                return self._parent.flow
        return self._term_flow

    @term_flow.setter
    def term_flow(self, term_flow):
        """
        Introduce term validation checking here if needed
        :param term_flow:
        :return:
        """
        if term_flow is None:
            if self.is_process:
                try:
                    self._term_flow = self.term_node.reference().flow
                except MultipleReferences as e:
                    try:
                        self._term_flow = self.term_node.reference(self._parent.flow).flow
                    except KeyError:
                        raise e

            elif self.is_frag:
                self._term_flow = None  # leave unspecified to plug into term's ref flow
            else:
                self._term_flow = self._parent.flow
        else:
            if self.is_process:
                try:
                    self._term_flow = self.term_node.reference(term_flow).flow
                except NoReference:  # we need to allow processes with no reference to be used as term nodes
                    self._term_flow = term_flow
                except KeyError:
                    raise MissingFlow(term_flow)
            elif self.is_frag:
                if term_flow == self.term_node.flow:  # don't need the inventory every time
                    self._term_flow = term_flow
                elif term_flow in (x.flow for x in self.term_node.cutoffs()):
                    self._term_flow = term_flow
                else:
                    raise MissingFlow(term_flow)
            else:
                self._term_flow = term_flow
        # this was causing us problems on delayed queries with MissingResource and it doesn't add anything
        # if self.valid and self.node_weight_multiplier == 0:  # we don't need to re-validate the flow
        #     print('Warning: 0 node weight multiplier for term of %s' % self._parent.external_ref)

    @property
    def direction(self):
        if self.is_process:
            return self._direction
        return comp_dir(self._parent.direction)

    @property
    def valid(self):
        if self.is_null:
            return True  # cutoff fragment flows should not report zero node weight
        return self.term_node.validate()

    @direction.setter
    def direction(self, value):
        if value is None:
            # this is the default: should set the direction by the reference.  Only non-none if from_json
            if self.is_process:
                rx = self.term_node.reference(self.term_flow)
                self._direction = rx.direction
                # for fg, invert direction doesn't make sense. for subfragments, direction is ignored
        else:
            self._direction = check_direction(value)

    '''
    def matches(self, exchange):
        """
        returns True if the exchange specifies the same process and flow as the term's process_ref and term_flow
        :param exchange:
        :return:
        """
        if self.is_null:
            return False
        if self.term_node.entity_type != 'process':
            return False
        return (self._term.external_ref == exchange.process.external_ref) and (self.term_flow.match(exchange.flow))

    def terminates(self, exchange):
        """
        Returns True if the exchange's termination matches the term's term_node, and the flows also match, and the
        directions are complementary.
        If the exchange does not specify a termination, returns True if the flows match and directions are comp.
        :param exchange:
        :return:
        """
        if self.term_flow.match(exchange.flow) and self.direction == comp_dir(exchange.direction):
            if exchange.termination is None:
                return True
            else:
                if self.is_null:
                    return False
                if self.term_node.entity_type != 'process':
                    return False
                if exchange.termination == self._term.external_ref:
                    return True
        return False

    def to_exchange(self):
        if self.is_null:
            return None
        return ExchangeValues(self.term_node, self.term_flow, self.direction, value=self.inbound_exchange_value)
    '''

    @property
    def is_local(self):
        """
        Fragment and termination have the same origin. Implies is_frag, since processes cannot be added to foregrounds
        :return:
        """
        if self.is_null:
            return False
        return self._parent.origin == self.term_node.origin

    @property
    def is_context(self):
        """
        termination is a context
        :return:
        """
        if self.is_null:
            return False
        return self.term_node.entity_type == 'context'

    @property
    def is_frag(self):
        """
        Termination is a fragment
        :return:
        """
        return (not self.is_null) and (self.term_node.entity_type == 'fragment')

    @property
    def is_process(self):
        """
        termination is a process
        :return:
        """
        return (not self.is_null) and (self.term_node.entity_type == 'process') and self.valid

    @property
    def is_emission(self):
        """
        Pending context refactor
        :return:
        """
        return self.is_context and self.term_node.elementary

    @property
    def is_fg(self):
        """
        Termination is parent
        :return:
        """
        return (not self.is_null) and (self.term_node is self._parent)

    @property
    def is_bg(self):
        """
        A term is "background" if the traversal does not include any descending fragments.  This condition is
        met in either of the following two cases:
         - the parent is background (no child flows) and the termination is to a process (i.e. not fg or cutoff)
         - the termination is to a fragment and descend is False
        old:
        # parent is marked background, or termination is a background fragment
        :return:
        """
        return (self._parent.is_background and self.is_process) or (self.is_subfrag and not self.descend)

    @property
    def term_is_bg(self):
        """
        Termination is local and background.  This is deprecated and always returns False.

        (Reason for its existence dates to when 'background' was a user-specified designation, and fragments were
        often terminated to a singleton-background fragment (fragment with an immediate background node and no children)

        The idea was simply to shorten the list of FragmentFlows generated in a traversal by removing the "connective
        tissue" fragment that terminated to the singleton background.  Now that background status is automatically
        determined by number of children, this is not reliable.)
        :return:
        """
        return False
        # return self.is_frag and self.is_local and self.term_node.is_background

    @property
    def is_subfrag(self):
        """
        Termination is a non-self fragment.  (we were excluding background frags too but that is outmoded)

        Old: Controversy around whether expression should be:
        self.is_frag and not (self.is_fg or self.is_bg or self.term_is_bg)  [current] or
        self.is_frag and (not self.is_fg) and (not self.is_bg)  [old; seems wrong]

        :return:
        """
        return self.is_frag and not self.is_fg  # or self.is_bg or self.term_is_bg)

    @property
    def is_null(self):
        return self._term is None

    @property
    def is_unresolved(self):
        return self._term is not None and self._term.entity_type == UNRESOLVED_ANCHOR_TYPE

    @property
    def descend(self):
        return self._descend

    @descend.setter
    def descend(self, value):
        if value is None:
            return
        if isinstance(value, bool):
            self._descend = value
            ''' # this whole section not needed- we can certainly cache LCIA scores for nondescend fragments,
            and we don't need to blow them away if descend is True; just ignore them.
            if value is True:
                self.clear_score_cache()  # if it's descend, it should have no score_cache
                # if it's not descend, the score gets computed (and not cached) during traversal
            '''
        else:
            raise ValueError('Descend setting must be True or False')

    @property
    def name(self):
        if self.is_null:
            name = self.term_flow['Name']
        elif self.is_context:
            name = '%s, %s' % (self.term_flow['Name'], self.term_node.name)
        else:
            name = self.term_node.name
        return name

    @property
    def term_ref(self):
        if self.is_null:
            return None
        elif self.is_context:
            return self.term_node.name
        return self.term_node.external_ref

    @property
    def flow_conversion(self):
        """
        express the parent's flow in terms of the quantity of the term flow.
        There are two ways to do this, each case involving the quantity relation on either the parent flow or the
        term flow, between the two quantities (parent flow's r.q. is the reference quantity; term flow's r.q. is the
        query quantity).

        In each case, we want the flow's native term manager to perform the conversion using ITS OWN canonical
        quantities.  The assumption is that the parent flow's r.q. is tied to our local LciaEngine, while the
        term flow's r.q. could be either local or remote.

        The QuantityRef.quantity_relation() implicitly assumes that the invoking quantity is the QUERY quantity, so
        the "forward" (natural parent->node) direction uses the remote flow's r.q. - but we do the "reverse" direction
        first because it's local.

        how to deal with scenario cfs? tbd
        problem is, the term doesn't know its own scenario

        :return: float = amount in term_flow ref qty that corresponds to a unit of fragment flow's ref qty
        """
        '''
        What are all the possibilities?
         the parent quantity knows a characterization for the parent flow w.r.t. the term quantity
         the parent quantity knows a characterization for the term flow w.r.t. the term quantity
         the term quantity knows a characterization for the parent flow w.r.t. the parent quantity
         the term quantity knows a characterization for the term flow w.r.t. the parent quantity

        "hey look at me, net calorific value. see that mass flow f4- a unit of it is worth 35 of me"
        is how the database is constructed.
        
        but each call to quantity_relation should check for both forward and reverse matches
        '''
        if not self.valid:
            logging.warning('Flow Conversion attempted on invalid term node %5.5s' % self._parent.uuid)
            return 1.0
        # if not self.term_flow.validate():
        #     return 1.0
        if self.term_flow is None:
            raise MissingFlow(self)
        if self._parent.flow is None:
            raise MalformedParent(self._parent)
        if self.term_flow.reference_entity == self._parent.flow.reference_entity:
            return 1.0
        parent_q = self._parent.flow.reference_entity
        term_q = self.term_flow.reference_entity
        if term_q is None:
            return 0.0

        # first - natural - ask our parent flow if fit can convert to term quantity
        try:
            rev = self._parent.flow.cf(term_q, context=self.term_node.external_ref)
            if rev == 0.0:
                rev = self._parent.flow.cf(term_q)

        except (QuantityRequired, NotImplementedError, ConversionReferenceMismatch):
            rev = None

        if rev:
            return rev

        # then ask the term_flow if it can convert to parent quantity
        try:
            fwd = self.term_flow.cf(parent_q)
        except (QuantityRequired, NotImplementedError, ConversionReferenceMismatch):
            fwd = None

        if fwd:
            return 1.0 / fwd

        # then ask if our parent qty can convert term_flow
        try:
            # I have no idea what unwritten rules are governing this context declaration - 2024-07-01
            rev_c = parent_q.quantity_relation(self.term_flow, term_q, context=(self.term_node.origin,
                                                                                self.term_node.external_ref))
        except (QuantityRequired, NotImplementedError):
            rev_c = None
        except ConversionReferenceMismatch:
            try:
                rev_c = parent_q.quantity_relation(self.term_flow, term_q, context=None)
            except ConversionReferenceMismatch:
                rev_c = None

        if rev_c:
            return 1.0 / rev_c.value

        # last, ask if remote quantity recognizes *our* flow
        print(' %s: flow_conversion: untested' % self._parent.link)
        try:
            fwd_c = term_q.quantity_relation(self._parent.flow, parent_q, context=(self.term_node.origin,
                                                                                   self.term_node.external_ref))
        except (QuantityRequired, NotImplementedError, ConversionReferenceMismatch):
            fwd_c = None

        if fwd_c:
            print('reverse q-hit')
            return fwd_c.value
        print(' %s: flow_conversion FAILED' % self._parent.link)
        raise FlowConversionError('Zero CF found relating %s to %s' % (self.term_flow, self._parent.flow))

    @property
    def id(self):
        if self.is_null:
            return None
        else:
            return self.term_node.external_ref

    @property
    def inbound_exchange_value(self):
        """
        This is only used for correcting fragment-term direction mismatches.
        This needs to be tested!
        :return:
        """
        if self.direction == self._parent.direction:
            return -1.0
        return 1.0

    @inbound_exchange_value.setter
    def inbound_exchange_value(self, val):
        raise NonConfigurableInboundEV

    @property
    def node_weight_multiplier(self):
        return self.flow_conversion / self.inbound_exchange_value

    @property
    def unit(self):
        if self.is_null:
            return '--'
        if self.term_node.entity_type == 'fragment':  # fg, bg, or subfragment
            return '%4g unit' % self.inbound_exchange_value
        return '%4g %s' % (self.inbound_exchange_value, self.term_flow.unit)  # process

    @property
    def observed_flows(self):
        for cf in self._parent.child_flows:
            yield DirectedFlow.from_observed(cf)

    def unobserved_exchanges(self, refresh=False):
        """
        Generator which yields exchanges from the term node's inventory that are not found among the child flows, for
          LCIA purposes

        Challenge here going forward: we made some kind of normative decision early on that terminations do not know
        their own scenarios, that the fragment maps scenario to termination. The problem is that now terminations
        cannot themselves carry out traversal on the term_node because they don't know what scenarios to pass.

        The upshot is that we cannot meaningfully compute "unobserved exchanges" for subfragments, since we don't
        know our scenario.

        :return:
        """
        if self.is_context:
            x = ExchangeValue(self._parent, self.term_flow, self._parent.direction, termination=self.term_node,
                              value=self.node_weight_multiplier)  # TODO: need to figure out how we are handling locales
            yield x
        elif self.is_frag:  # fragments can have unobserved exchanges too! (CAN THEY?)
            # this code is unreachable because self.is_frag returns a null LciaResult in compute_unit_score()
            for x in []:
                yield x
        else:
            if self.is_bg:  # or len(list(self._parent.child_flows)) == 0:
                # ok we're bringing it back but only because it is efficient to cache lci
                for x in self.term_node.lci(ref_flow=self.term_flow, refresh=refresh):
                    yield x
            else:
                for x in self.term_node.unobserved_lci(self.observed_flows, ref_flow=self.term_flow):
                    yield x  # this should forward out any cutoff exchanges

    def _fallback_lcia(self, quantity_ref, locale, **kwargs):
        """
        Uses term node inventory if no background is available
        :param quantity_ref:
        :param locale:
        :param kwargs:
        :return:
        """
        print('WARNING- BackgroundRequired - using fallback lcia %s' % self._parent.link)
        child_flows = set((k.flow.external_ref, k.direction) for k in self._parent.child_flows)
        inv = [x for x in self.term_node.inventory(ref_flow=self.term_flow)
               if (x.flow.external_ref, x.direction) not in child_flows]
        res = quantity_ref.do_lcia(inv, locale=locale, **kwargs)
        return res

    def compute_unit_score(self, quantity_ref, refresh=False, **kwargs):
        """
        four different ways to do this.
        0- we are a subfragment-- no direct impacts unless non-descend, which is caught earlier
        1- parent is bg: ask catalog to give us bg_lcia (process or fragment)
        2- get fg lcia for unobserved exchanges

        If
        :param quantity_ref:
        :param refresh:
        :return:
        """
        if self.is_context:
            try:
                locale = self._parent['SpatialScope']
            except KeyError:
                locale = self.term_flow.locale
            x = ExchangeValue(self._parent, self.term_flow, self._parent.direction, termination=self.term_node,
                              value=self.node_weight_multiplier)  # TODO: need to figure out how we are handling locales
            res = do_lcia(quantity_ref, [x], locale=locale, refresh=refresh, **kwargs)

        else:
            # OK, so we are not frag and we are not context and we are not null-- we are process!
            try:
                locale = self.term_node['SpatialScope']
            except KeyError:
                locale = 'GLO'

            try:
                res = self.term_node.bg_lcia(quantity_ref, observed=self.observed_flows, ref_flow=self.term_flow,
                                             refresh=refresh, locale=locale, **kwargs)
            except (QuantityRequired, EntityNotFound, NotImplementedError):
                try:
                    res = quantity_ref.do_lcia(self.unobserved_exchanges(refresh=refresh), locale=locale,
                                               refresh=refresh, **kwargs)
                except (BackgroundRequired, NotImplementedError):
                    res = self._fallback_lcia(quantity_ref, locale, **kwargs)
            except BackgroundRequired:
                res = self._fallback_lcia(quantity_ref, locale, **kwargs)

        if isinstance(res, list):
            [k.scale_result(self.inbound_exchange_value) for k in res]
        else:
            res.scale_result(self.inbound_exchange_value)
        return res

    def score_cache(self, quantity=None, refresh=False, **kwargs):
        """
        only process-terminations are cached
        remote fragments that come back via the API can have cached scores as well, but local subfragments should not
        get cached.

        :param quantity:
        :param ignore_uncached:
        :param refresh: If True, re-compute unit score even if it is already present in the cache.
        :param kwargs:
        :return:
        """
        if quantity is None:
            return self._score_cache

        if self.is_null or self.is_fg:
            return LciaResult(quantity)

        if not self.valid:
            raise UnresolvedAnchor

        if refresh:
            self._score_cache.pop(quantity, None)

        if quantity in self._score_cache:
            return self._score_cache[quantity]
        else:
            if self.is_frag:  # but not fg, ergo subfrag
                raise UnCachedScore(quantity)
            else:
                '''
                # This refresh situation is a problem.  On the one hand, if we don't pass refresh on to do_lcia,
                then there's no way to clear "seen cfs" on flow refs.  On the other hand, passing it through recursively
                from frag_flow_lcia means we will continually "see" and then "refresh" seen cfs on every flow, for every
                fragment we traverse. This is just an efficiency bomb.  We need to find a better way to refresh scores
                that won't suffer from this problem- but unfortunately I can't think of anyway to track that state 
                mid-traversal. 
                
                note: additionally, refreshing "seen cfs" and refreshing fragment unit scores are separate
                tasks and should not use the same keyword argument.  In both cases, passing 'refresh' to a recursive
                traversal results in highly duplicated computation.  
                
                The solution is to no longer support 'refresh' during traversal or any recursive operation.  However,
                we retain it here because we still want to be able to do both of:
                 - refresh seen cfs during calls to do_lcia() in compute_unit_score()
                 - refresh cached LCI during calls to lci() in _unobserved_exchanges()
                
                As to the other uses:
                 - individual termination scores can be refreshed using this method score_cache()
                 - entire foreground scores can be refreshed using the clear_unit_scores() implementation method
                 - flow CFs (apart from those included in specified terminations) can only be refreshed by manually 
                    calling do_lcia() with an inventory that includes them.  This is obviously not ideal, and a new 
                    solution should be sought.  
                '''
                res = self.compute_unit_score(quantity, refresh=refresh, **kwargs)
            if isinstance(res, list):
                for k in res:
                    self._score_cache[k.quantity] = k
            else:
                self._score_cache[quantity] = res
            return self._score_cache[quantity]

    def score_cache_items(self):
        return self._score_cache.items()

    def lcia(self):
        for k, v in self.score_cache_items():
            print('%s' % v)

    def reset_score(self, lcia):
        self._score_cache.pop(lcia, None)

    def clear_score_cache(self):
        self._score_cache.clear()

    def _serialize_score_cache(self):
        """
        Score cache contains an LciaResults object, which works as a dict.
        serialization should preserve order, which prohibits using a simple dict
        :return: a list to be serialized directly
        """
        score_cache = []
        for q in self._score_cache.indices():
            res = self._score_cache[q]
            score_cache.append({'quantity': {'origin': res.quantity.origin,
                                             'externalId': res.quantity.external_ref},
                                'score': res.total()})
        return score_cache

    def add_lcia_score(self, quantity, score, scenario=None):
        res = LciaResult(quantity, scenario=scenario)
        res.add_summary(self._parent.external_ref, self._parent, 1.0, score)
        self._score_cache[quantity] = res

    def _deserialize_score_cache(self, fg, sc, scenario):
        self._score_cache = LciaResults(self._parent)
        for i in sc:
            q = fg.catalog_ref(i['quantity']['origin'], i['quantity']['externalId'], entity_type='quantity')
            self.add_lcia_score(q, i['score'], scenario=scenario)

    def _term_flow_block(self):
        if self.term_flow.origin == self.term_node.origin:
            return self.term_flow.external_ref
        else:
            return {
                'origin': self.term_flow.origin,
                'externalId': self.term_flow.external_ref
            }

    def serialize(self, save_unit_scores=False):
        if self.is_null:
            return {}
        if self.is_context:
            j = {
                'origin': 'foreground',
                'context': self.term_node.name
            }
        else:
            j = {
                'origin': self.term_node.origin,
                'externalId': self.term_node.external_ref
            }
            if self.is_local:
                j['origin'] = 'foreground'  # override

        # saving term_flow: for subfragments, we save it only it it's specified
        if self.is_frag:
            if self._term_flow is not None:
                j['termFlow'] = self._term_flow_block()
        elif self.term_flow != self._parent.flow:
            j['termFlow'] = self._term_flow_block()

        if self.direction != comp_dir(self._parent.direction):
            j['direction'] = self.direction
        if self._descend is False:
            j['descend'] = False
        if self._parent.is_background and save_unit_scores and len(self._score_cache) > 0:
            j['scoreCache'] = self._serialize_score_cache()
        return j

    def to_anchor(self, save_unit_scores=False, group=None):
        if self.is_null:
            return Anchor.null()
        d = {'descend': self.descend}
        if self._parent.is_background and save_unit_scores and len(self._score_cache) > 0:
            d['score_cache'] = self._serialize_score_cache()
        if self.is_context:
            d['context'] = self.term_node.as_list()
            if self.term_flow != self._parent.flow:
                d['anchor_flow'] = EntityRef.from_entity(self.term_flow)
            return Anchor(**d)
        else:
            if self.is_frag:
                if self.term_flow != self.term_node.flow:
                    d['anchor_flow'] = EntityRef.from_entity(self.term_flow)
            else:
                if self.term_flow != self._parent.flow:
                    d['anchor_flow'] = EntityRef.from_entity(self.term_flow)
            d['node'] = EntityRef.from_entity(self.term_node)
            return Anchor(**d)

    def __eq__(self, other):
        """
        Terminations are equal if they are both null, both fg, or if term_node, term_flow, direction and descend match
        :param other:
        :return:
        """
        if self is other:
            return True
        if not isinstance(other, FlowTermination):
            return False
        if self.is_null:
            if other.is_null:
                return True
            return False
        if self.is_fg:
            if other.is_fg:
                return True
            return False
        return (self.term_node.external_ref == other.term_node.external_ref and
                self.term_flow == other.term_flow and
                self.direction == other.direction and
                self.descend == other.descend)  # probably want to remove this

    def __str__(self):
        """

        :return:
          '---:' = fragment I/O
          '-O  ' = foreground node
          '-*  ' = process
          '-#  ' - sub-fragment (aggregate)
          '-#::' - sub-fragment (descend)
          '-B ' - terminated background
          '--C ' - cut-off background
          '--? ' - ungrounded catalog ref
        """
        if self.is_null:
            term = '---:'  # fragment IO
        elif self.is_fg:
            term = '-O  '
        elif self.is_context:
            if self.is_emission:
                term = '-== '
            elif self.term_node is NullContext:
                term = '-)  '
            else:
                # TODO: intermediate contexts don't present as cutoffs (because is_null is False)
                term = '-cx '
        elif self.term_node.entity_type == 'process':
            if self.is_bg:
                term = '-B* '
            else:
                term = '-*  '
        elif self.term_node.entity_type == 'fragment':
            if self.descend:
                term = '-#::'
            else:
                term = '-#  '
        elif self.term_node.entity_type == UNRESOLVED_ANCHOR_TYPE:
            term = '--? '
        else:
            raise TypeError('I Do not understand this term for frag %.7s' % self._parent.uuid)
        return term
