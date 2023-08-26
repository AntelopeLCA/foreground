"""
Client for the oryx Foreground server

This is to be the same as the XdbServer, just with different methods defined
"""
from antelope_core.providers.xdb_client import XdbClient, _ref
from antelope_core.providers.xdb_client.xdb_entities import XdbEntity
from antelope_core.implementations import BasicImplementation
from antelope.models import OriginCount

from ..interfaces import AntelopeForegroundInterface
from ..refs.fragment_ref import FragmentRef

from ..models import LcForeground, FragmentFlow, FragmentRef as FragmentRefModel, MissingResource, FragmentEntity

from requests.exceptions import HTTPError


class OryxEntity(XdbEntity):
    def make_ref(self, query):
        if self._ref is not None:
            return self._ref

        if self.entity_type == 'fragment':
            args = {k: v for k, v in self._model.properties.items()}
            if hasattr(self._model, 'flow'):
                flow = self._model.flow
                direction = self._model.direction
            else:
                flow = args.pop('flow')
                direction = args.pop('direction')

            ref = FragmentRef(self.external_ref, query,
                              flow=query.get(flow['entity_id']), direction=direction, **args)

            self._ref = ref
            return ref
        return super(OryxEntity, self).make_ref(query)


class OryxClient(XdbClient):

    _base_type = OryxEntity

    def __init__(self, *args, catalog=None, **kwargs):
        """
        Not sure we need the catalog yet, but LcResource gives it to us, so let's hold on to it
        :param args:
        :param catalog:
        :param kwargs:
        """
        self._catalog = catalog
        super(OryxClient, self).__init__(*args, **kwargs)

    @property
    def query(self):
        return self._catalog.query(self.ref)

    def make_interface(self, iface):
        if iface == 'foreground':
            return OryxFgImplementation(self)
        return super(OryxClient, self).make_interface(iface)


class OryxFgImplementation(BasicImplementation, AntelopeForegroundInterface):
    """
    We don't need to REimplement anything in XdbClient because oryx server should behave the same to the same routes
    """

    @property
    def delayed(self):
        return self._archive.delayed

    @property
    def unresolved(self):
        return self._archive.unresolved

    def get(self, external_ref, **kwargs):
        return self._archive.query.get(external_ref, **kwargs)

    def fragments(self, **kwargs):
        llargs = {k.lower(): v for k, v in kwargs.items()}
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel, 'fragments', **llargs)]

    def post_foreground(self, fg, save_unit_scores=False):
        pydantic_fg = LcForeground.from_foreground_archive(fg.archive, save_unit_scores=save_unit_scores)
        return self._archive.r.post_return_one(pydantic_fg.dict(), OriginCount, 'post_foreground')

    def save(self):
        return self._archive.r.post_return_one(None, bool, 'save_foreground')

    def restore(self):
        return self._archive.r.post_return_one(None, bool, 'restore_foreground')

    def missing(self):
        return self._archive.r.get_many(MissingResource, 'missing')

    def get_reference(self, key):
        try:
            parent = self._archive.r.get_one(FragmentRefModel, _ref(key), 'reference')
        except HTTPError as e:
            if e.args[0] == 400:
                return None
            raise e
        return self._archive.get_or_make(parent)

    def get_fragment(self, key):
        """
        detailed version of a fragment
        :param key:
        :return:
        """
        return self._archive.r.get_one(FragmentEntity, 'fragments', _ref(key))

    def top(self, key, **kwargs):
        return self._archive.get_or_make(self._archive.r.get_one(FragmentRefModel, _ref(key), 'top'))

    def traverse(self, fragment, scenario=None, **kwargs):
        return self._archive.r.get_many(FragmentFlow, _ref(fragment), 'traverse', scenario=scenario, **kwargs)
