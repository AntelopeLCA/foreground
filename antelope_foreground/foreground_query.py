from antelope import InvalidQuery, EntityNotFound
from antelope_core.catalog_query import CatalogQuery
from antelope_core.contexts import NullContext

from .interfaces.iforeground import AntelopeForegroundInterface
from .models import FragmentFlow as FragmentFlowModel
from .fragment_flows import FragmentFlow
from .terminations import FlowTermination



class ForegroundNotSafe(Exception):
    """
    This foreground has not been loaded yet. keep our references unresolved
    """
    pass


class ForegroundQuery(CatalogQuery, AntelopeForegroundInterface):
    """
    Add foreground interface to query object.
    We also need to add lubricating code to translate between pydantic models and operable objects
    """
    def make_term_from_anchor(self, parent, anchor, scenario):
        if anchor.is_null:
            term = FlowTermination.null(parent)
        else:
            if anchor.anchor_flow:
                term_flow = self.make_ref(self.get(anchor.anchor_flow.entity_id,
                                                   origin=anchor.anchor_flow.origin))
            else:
                term_flow = None
            if anchor.context:
                term = FlowTermination(parent, self.get_context(anchor.context), term_flow=term_flow,
                                       descend=anchor.descend)
            elif anchor.node:
                term_node = self.make_ref(self.get(anchor.node.entity_id,
                                                   origin=anchor.node.origin))
                term = FlowTermination(parent, term_node, term_flow=term_flow,
                                       descend=anchor.descend)
            else:
                term = FlowTermination.null(parent)
        if anchor.score_cache:
            ar = self._catalog.get_archive(self.origin)
            term._deserialize_score_cache(ar, anchor.score_cache, scenario)

        return term

    def _make_fragment_flow(self, ff_model):
        if isinstance(ff_model, FragmentFlowModel):
            frag = self.make_ref(self.get(ff_model.fragment.entity_id, origin=ff_model.fragment.origin))

            # we have to do this manually because legacy code is terrible
            term = self.make_term_from_anchor(frag, ff_model.anchor, ff_model.anchor_scenario)

            return FragmentFlow(frag, ff_model.magnitude, ff_model.node_weight, term,
                                ff_model.is_conserved, match_ev=ff_model.scenario, match_term=ff_model.anchor_scenario)
        return ff_model

    def traverse(self, fragment, scenario=None, **kwargs):
        ffs = super(ForegroundQuery, self).traverse(fragment, scenario=scenario, **kwargs)
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

    def _perform_query(self, itype, attrname, exc, *args, **kwargs):
        if self._catalog.is_in_queue(self._home):
            raise QueryIsDelayed(self.origin, self._home)
        return super(DelayedQuery, self)._perform_query(itype, attrname, exc, *args, **kwargs)
