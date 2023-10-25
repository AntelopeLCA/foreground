from antelope import InvalidQuery
from antelope_core.catalog_query import CatalogQuery
from antelope_core.contexts import NullContext

from .interfaces.iforeground import AntelopeForegroundInterface


class ForegroundNotSafe(Exception):
    """
    This foreground has not been loaded yet. keep our references unresolved
    """
    pass


class ForegroundQuery(CatalogQuery, AntelopeForegroundInterface):
    """
    Add foreground interface to query object
    """

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        ress = super(ForegroundQuery, self).fragment_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        return self._cycle_through_ress(ress, fragment, quantity_ref)


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
