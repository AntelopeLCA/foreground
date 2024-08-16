import logging

from antelope import InvalidQuery, EntityNotFound, ItemNotFound, QuantityRequired
from antelope_core.catalog_query import CatalogQuery
from antelope_core.contexts import NullContext
from antelope.models import Characterization as CharacterizationModel

from .interfaces.iforeground import AntelopeForegroundInterface
from .models import FragmentFlow as FragmentFlowModel, FragmentBranch as FragmentBranchModel
from .fragment_flows import FragmentFlow
from .terminations import FlowTermination


class ForegroundNotSafe(Exception):
    """
    This foreground has not been loaded yet. keep our references unresolved
    """
    pass


class FragmentBranch(object):
    def __init__(self, node, anchor, group='', scenario=None, magnitude=None, is_cutoff=None):
        self.node = node
        self.anchor = anchor
        self.group = group
        self.scenario = scenario
        self.magnitude = magnitude
        self.is_cutoff = bool(is_cutoff)

    @property
    def parent(self):
        return self.node.reference_entity

    @property
    def name(self):
        return self.anchor.name

    @property
    def unit(self):
        return self.node.flow.unit

    @property
    def is_balance_flow(self):
        return self.node.is_balance


class ForegroundQuery(CatalogQuery, AntelopeForegroundInterface):
    def cascade(self, origin):
        if origin in self._catalog.foregrounds:
            return self._catalog.foreground(origin)
        return super(ForegroundQuery, self).cascade(origin)

    def characterize(self, flowable, ref_quantity, query_quantity, value, context=None, location='GLO', **kwargs):
        """
        Now that we are back in the foreground, we want to go back to the implementation's own characterize.
        we overrule CatalogQuery.characterize() and go back to the abstract interface.
        We also want to make sure that we get rid of stale characterizations and unit scores.
        SEE? I TOLD you flows_for_flowable was important.
        {all of this goofy stuff would go away with a proper graph database, grumble}
        :param flowable:
        :param ref_quantity:
        :param query_quantity:
        :param value:
        :param context:
        :param location:
        :param kwargs:
        :return:
        """
        cf = self._perform_query('quantity', 'characterize', QuantityRequired,
                                 flowable, ref_quantity, query_quantity, value,
                                 context=context, location=location, **kwargs)
        qq = self.get_canonical(query_quantity)
        if qq.is_lcia_method:
            self._catalog.clear_unit_scores(qq)
        for flow in self._tm.flows_for_flowable(flowable):
            flow.clear_chars(qq)
        if isinstance(cf, CharacterizationModel):
            return self._resolve_cf(cf)
        else:
            return cf

    """
    Add foreground interface to query object.
    We also need to add lubricating code to translate between pydantic models and operable objects
    """
    def make_term_from_anchor(self, parent, anchor, scenario, flow_conversion=None):
        if anchor.is_null:
            term = FlowTermination.null(parent)
        else:
            if anchor.anchor_flow:
                term_flow = self.get(anchor.anchor_flow.entity_id,
                                     origin=anchor.anchor_flow.origin)
            else:
                term_flow = None

            """
            def characterize(self, flowable, ref_quantity, query_quantity, value, context=None, location='GLO', **kws):
            """
            if anchor.context:
                cx = self.get_context(anchor.context)
                if term_flow is not None and flow_conversion is not None and flow_conversion != 1.0:
                    print('Term CF %s : %s [%g]' % (parent.link, cx, flow_conversion))
                    # log reported flow conversion.  Some shit to sort out w/r/t/ context
                    # we want this characterization to apply locally
                    super(ForegroundQuery, self).characterize(parent.flow.name, parent.flow.reference_entity,
                                                              term_flow.reference_entity,
                                                              flow_conversion, context=cx)

                term = FlowTermination(parent, cx, term_flow=term_flow,
                                       descend=anchor.descend)
            elif anchor.node:
                if anchor.node.link == parent.link:  # self-termination
                    term_node = parent
                else:
                    term_node = self.get(anchor.node.entity_id, origin=anchor.node.origin)
                if flow_conversion is not None and flow_conversion != 1.0:
                    rx = term_node.reference(term_flow)
                    print('Term CF %s : %s [%g]' % (parent.link, term_node.link, flow_conversion))
                    # log reported flow conversion.  Some shit to sort out w/r/t/ context
                    super(ForegroundQuery, self).characterize(parent.flow.name, parent.flow.reference_entity,
                                                              rx.flow.reference_entity,
                                                              flow_conversion,
                                                              context=(term_node.origin, term_node.external_ref))

                term = FlowTermination(parent, term_node, term_flow=term_flow,
                                       descend=anchor.descend)
            else:
                term = FlowTermination.null(parent)
        if anchor.score_cache:
            ar = self._catalog.get_archive(self.origin)
            term._deserialize_score_cache(ar, anchor.score_cache, scenario)

        if parent.is_entity:
            logging.warning('make_term_from_anchor called by fragment entity %s' % parent.link)
        else:
            parent._anchors[scenario] = term  # just deal with it
        return term

    def _make_fragment_branch(self, n):
        if isinstance(n, FragmentBranchModel):
            frag = self.get(n.node.entity_id, origin=n.node.origin)
            term = self.make_term_from_anchor(frag, n.anchor, n.scenario, 1.0)
            return FragmentBranch(frag, term, group=n.group, scenario=n.scenario, magnitude=n.magnitude,
                                  is_cutoff=n.is_cutoff)
        return n

    def nodes(self, origin=None, **kwargs):
        ns = super(ForegroundQuery, self).nodes(origin=origin, **kwargs)
        return [self._make_fragment_branch(n) for n in ns]

    def _make_fragment_flow(self, ff_model):
        if isinstance(ff_model, FragmentFlowModel):
            frag = self.get(ff_model.fragment.entity_id, origin=ff_model.fragment.origin)

            # we have to do this manually because legacy code is terrible
            term = self.make_term_from_anchor(frag, ff_model.anchor, ff_model.anchor_scenario, ff_model.flow_conversion)

            the_ff = FragmentFlow(frag, ff_model.magnitude, ff_model.node_weight, term, ff_model.is_conserved,
                                  match_ev=ff_model.scenario, match_term=ff_model.anchor_scenario,
                                  flow_conversion=ff_model.flow_conversion)

            if len(ff_model.subfragments) > 0:
                subfrags = [self._make_fragment_flow(FragmentFlowModel(**ff)) for ff in ff_model.subfragments]
                the_ff.aggregate_subfragments(subfrags, (ff_model.anchor_scenario,))

            return the_ff

        return ff_model

    def traverse(self, fragment, scenario=None, **kwargs):
        ffs = super(ForegroundQuery, self).traverse(fragment, scenario=scenario, **kwargs)
        return [self._make_fragment_flow(ff) for ff in ffs]

    def cutoff_flows(self, fragment, scenario=None, **kwargs):
        ffs = super(ForegroundQuery, self).cutoff_flows(fragment, scenario=scenario, **kwargs)
        return [self._make_fragment_flow(ff) for ff in ffs]

    def activity(self, fragment, scenario=None, **kwargs):
        ffs = super(ForegroundQuery, self).activity(fragment, scenario=scenario, **kwargs)
        return [self._make_fragment_flow(ff) for ff in ffs]

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        ress = super(ForegroundQuery, self).fragment_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        return self._cycle_through_ress(ress, fragment, quantity_ref)

    def flowable(self, item):
        return self._tm.get_flowable(item)

    def __getitem__(self, item):
        try:
            return self.get(item)
        except EntityNotFound:
            return None  # I know, it's so bad. Plan is to break this and use downstream errors to expunge the practice


class QueryIsDelayed(InvalidQuery):
    """
    This indicates a foreground that has been queued for initialization (recursively)-- should become initialized
    before the current operation is concluded, thus allowing the DelayedQuery to function
    """
    pass


class MissingResource(InvalidQuery):
    """
    This indicates an UnknownOrigin exception was encountered when attempting to resolve a reference-- requires
    intervention from the user to supply a resource to fulfill the DelayedQuery
    """
    pass


class DelayedQuery(ForegroundQuery):
    """
    unresolved query that can sub itself in
    all it needs to do is raise a validation error until it's switched on
    """
    _home = None

    def __init__(self, origin, catalog, home, **kwargs):
        self._home = home
        super(DelayedQuery, self).__init__(origin, catalog, **kwargs)

    def get_context(self, term, **kwargs):
        cx = self._catalog.lcia_engine[term]
        if cx is None:
            return NullContext
        return cx

    def validate(self):
        if self._catalog.is_in_queue(self._home):
            return True  # this has to be true in order for the ref to operate while it is delayed
        try:
            return super(DelayedQuery, self).validate()
        except MissingResource:
            return True  # likewise

    def get_item(self, external_ref, item):
        try:
            return super(DelayedQuery, self).get_item(external_ref, item)
        except MissingResource:
            raise ItemNotFound

    def is_lcia_engine(self, **kwargs):
        try:
            return super(DelayedQuery, self).is_lcia_engine(**kwargs)
        except MissingResource:
            return False

    def _perform_query(self, itype, attrname, exc, *args, **kwargs):
        if self._catalog.is_in_queue(self._home):
            raise QueryIsDelayed(self.origin, self._home)
        return super(DelayedQuery, self)._perform_query(itype, attrname, exc, *args, **kwargs)
