"""
Client for the oryx Foreground server

This is to be the same as the XdbServer, just with different methods defined
"""
from antelope_core.providers.xdb_client import XdbClient
from antelope_core.providers.xdb_client.xdb_entities import XdbEntity
from antelope_core.implementations import BasicImplementation
from antelope.models import OriginCount

from ..interfaces import AntelopeForegroundInterface
from ..refs.fragment_ref import FragmentRef

from ..models import LcForeground, FragmentFlow, FragmentRef as FragmentRefModel


class OryxEntity(XdbEntity):
    def make_ref(self, query):
        if self._ref is not None:
            return self._ref

        if self.entity_type == 'fragment':
            args = {k: v for k, v in self._model.properties.items()}
            ref = FragmentRef(self.external_ref, query, reference_entity=self._model.parent, **args)
            ref.set_config(query.get(self._model.flow.external_ref), self._model.direction)
            self._ref = ref
            return ref
        return super(OryxEntity, self).make_ref(query)



class OryxClient(XdbClient):

    _base_type = OryxEntity

    def make_interface(self, iface):
        if iface == 'foreground':
            return OryxFgImplementation(self)
        return super(OryxClient, self).make_interface(iface)


def _ref(obj):
    """
    URL-ize input argument
    :param obj:
    :return:
    """
    if hasattr(obj, 'external_ref'):
        return obj.external_ref
    return str(obj)


class OryxFgImplementation(BasicImplementation, AntelopeForegroundInterface):
    """
    We don't need to REimplement anything in XdbClient because oryx server should behave the same to the same routes
    """
    def fragments(self, **kwargs):
        llargs = {k.lower(): v for k, v in kwargs.items()}
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel, 'fragments', **llargs)]

    def post_foreground(self, fg, save_unit_scores=False):
        pydantic_fg = LcForeground.from_foreground_archive(fg.archive, save_unit_scores=save_unit_scores)
        return self._archive.r.post_return_one(pydantic_fg.dict(), OriginCount, 'post_foreground')

    def traverse(self, fragment, scenario=None, **kwargs):
        return self._archive.r.get_many(FragmentFlow, _ref(fragment), 'traverse', scenario=scenario, **kwargs)
