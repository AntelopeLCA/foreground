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
    pass


class QueryIsDelayed(InvalidQuery):
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
        return super(DelayedQuery, self).validate()

    def _perform_query(self, itype, attrname, exc, *args, strict=False, **kwargs):
        if self._catalog.is_in_queue(self._home):
            raise QueryIsDelayed(self.origin, self._home)
        return super(DelayedQuery, self)._perform_query(itype, attrname, exc, *args, strict=strict, **kwargs)
