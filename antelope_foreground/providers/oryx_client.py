"""
Client for the oryx Foreground server

This is to be the same as the XdbServer, just with different methods defined
"""
from typing import List

from antelope_core.providers.xdb_client import XdbClient, _ref
from antelope_core.providers.xdb_client.xdb_entities import XdbEntity
from antelope_core.implementations import BasicImplementation
from antelope.models import OriginCount, LciaResult as LciaResultModel, EntityRef

from ..interfaces import AntelopeForegroundInterface
from ..refs.fragment_ref import FragmentRef

from ..models import (LcForeground, FragmentFlow, FragmentRef as FragmentRefModel, MissingResource,
                      FragmentBranch, FragmentEntity)

from requests.exceptions import HTTPError


class MalformedOryxEntity(Exception):
    """
    something is wrong with the entity model
    """
    pass


class OryxEntity(XdbEntity):
    def make_ref(self, query):
        if self._ref is not None:
            return self._ref

        if self.entity_type == 'fragment':
            """
            This is complicated because there are a couple different possibilities for the model type.
            If the model is a FragmentEntity, then it contains a 'flow' attribute which is actually a FlowEntity,
            but if the model is a FragmentRef, then its flow and direction are stored along with other 
            entity properties, and they will not be converted into pydantic types but kept as dicts
            """
            args = {k: v for k, v in self._model.properties.items()}
            f = args.pop('flow', None)
            d = args.pop('direction', None)
            if f is None:
                if hasattr(self._model, 'flow'):
                    flow = query.cascade(self._model.flow.origin).get(self._model.flow.entity_id)
                    direction = self._model.direction
                else:
                    raise MalformedOryxEntity(self.link)
            else:
                flow = query.cascade(f['origin']).get(f['entity_id'])
                direction = d

            ref = FragmentRef(self.external_ref, query,
                              flow=flow, direction=direction, **args)

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
    (but that means we need to reimplement everything in OryxServer)
    """
    def _o(self, obj=None):
        """
        Key difference between the Xdb implementation is: the xdb implementation is strongly tied to its origin,
        but the foreground can refer to entities with various origins.

        To handle this, we *masquerade* the query (to the primary origin) with the entity's authentic origin (just as
        we do with local.qdb). this happens in catalog query through the use of _grounded_query()

        then in our requester we unset_origin() and issue origin, ref explicitly.

        _o is the mechanism for this.

        Implies that client code is expected to supply a true entity and not a string ref-- this is potentially a
        problem

        returns either the object's origin, if it is an object, or the archive's ref

        :param obj:
        :return:
        """
        if hasattr(obj, 'origin'):
            return obj.origin
        return self._archive.ref

    @property
    def delayed(self):
        return self._archive.delayed

    @property
    def unresolved(self):
        return self._archive.unresolved

    def get(self, external_ref, **kwargs):
        return self._archive.query.get(external_ref, **kwargs)

    # foreground resource operations-- non-masqueraded
    def fragments(self, **kwargs):
        llargs = {k.lower(): v for k, v in kwargs.items()}
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel, 'fragments', **llargs)]

    def post_foreground(self, fg, save_unit_scores=False):
        pydantic_fg = LcForeground.from_foreground_archive(fg.archive, save_unit_scores=save_unit_scores)
        return self._archive.r.post_return_one(pydantic_fg.dict(), OriginCount, 'post_foreground')

    def post_entity_refs(self, post_ents: List[EntityRef]):
        return self._archive.r.post_return_one([p.dict() for p in post_ents], OriginCount, 'entity_refs')

    def save(self):
        return self._archive.r.post_return_one(None, bool, 'save_foreground')

    def restore(self):
        return self._archive.r.post_return_one(None, bool, 'restore_foreground')

    def missing(self):
        return self._archive.r.origin_get_many(MissingResource, 'missing')  # no origin required

    # Entity operations- masqueraded
    def get_reference(self, key):
        try:
            # !TODO! key will always be an external_ref so _o(key) will fail
            parent = self._archive.r.origin_get_one(FragmentRefModel, self._o(key), _ref(key), 'reference')
        except HTTPError as e:
            if e.args[0] == 400:
                return None
            raise e
        return self._archive.get_or_make(parent)

    def get_fragment(self, fragment):
        """
        detailed version of a fragment
        :param fragment:
        :return:
        """
        return self._archive.r.origin_get_one(FragmentEntity, self._o(fragment), 'fragments', _ref(fragment))

    def top(self, fragment, **kwargs):
        return self._archive.get_or_make(self._archive.r.origin_get_one(FragmentRefModel,
                                                                        self._o(fragment), _ref(fragment), 'top'))

    def scenarios(self, fragment, **kwargs):
        return self._archive.r.origin_get_many(str, self._o(fragment), _ref(fragment),
                                               'scenarios', **kwargs)

    def traverse(self, fragment, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(FragmentFlow, self._o(fragment), _ref(fragment),
                                               'traverse', scenario=scenario, **kwargs)

    def activity(self, fragment, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(FragmentFlow, self._o(fragment), _ref(fragment),
                                               'activity', scenario=scenario, **kwargs)

    def tree(self, fragment, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(FragmentBranch, self._o(fragment), _ref(fragment),
                                               'tree', scenario=scenario, **kwargs)

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, mode=None, **kwargs):
        if mode == 'detailed':
            return self.detailed_lcia(fragment,quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'flat':
            return self.flat_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'stage':
            return self.stage_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'anchor':
            return self.anchor_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        return self._archive.r.origin_get_many(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                               'fragment_lcia',
                                               _ref(quantity_ref), scenario=scenario, **kwargs)

    def detailed_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                               'detailed_lcia',
                                               _ref(quantity_ref), scenario=scenario, **kwargs)

    def flat_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                               'lcia',
                                               _ref(quantity_ref), scenario=scenario, **kwargs)

    def stage_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                               'stage_lcia',
                                               _ref(quantity_ref), scenario=scenario, **kwargs)

    def anchor_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        return self._archive.r.origin_get_many(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                               'anchor_lcia',
                                               _ref(quantity_ref), scenario=scenario, **kwargs)
