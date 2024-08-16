"""
Client for the oryx Foreground server

This is to be the same as the XdbServer, just with different methods defined
"""
import logging

from antelope import UnknownOrigin, comp_dir
from antelope_core.providers.xdb_client import XdbClient, _ref
from antelope_core.providers.xdb_client.xdb_entities import XdbEntity
from antelope_core.implementations import BasicImplementation
from antelope.models import OriginCount, LciaResult as LciaResultModel, EntityRef, FlowEntity

from ..interfaces import AntelopeForegroundInterface
from ..refs.fragment_ref import FragmentRef, ParentFragment
from .lc_foreground import AmbiguousReference, FragmentNotFound

from ..models import (LcForeground, FragmentFlow, FragmentRef as FragmentRefModel, MissingResource,
                      FragmentBranch, FragmentEntity, Anchor, ForegroundRelease, Observation)

from requests.exceptions import HTTPError
from uuid import uuid4


class MalformedOryxEntity(Exception):
    """
    something is wrong with the entity model
    """
    pass


class OryxEntity(XdbEntity):
    @property
    def uuid(self):
        if hasattr(self._model, 'entity_uuid'):
            return self._model.entity_uuid
        return None

    def make_ref(self, query):
        if self._ref is not None:
            return self._ref

        if self.entity_type == 'fragment':
            """
            This is complicated because there are a couple different possibilities for the model type.
            If the model is a FragmentEntity, then it contains a 'flow' attribute which is actually a FlowEntity,
            but if the model is a FragmentRef, then its flow and direction are stored along with other 
            entity properties, and they will not be converted into pydantic types but kept as dicts
            
            we also need to handle parents, with reference fragments (having None parents) being replaced in the API
            layer with 404 errors and thereby getting caught and replaced with ParentFragment exceptions... 
            
            and also UUIDs which arrive from Entity models as properties and from FragmentRef models as entity_uuid
            attributes
            """
            args = {k: v for k, v in self._model.properties.items()}
            f = args.pop('flow', None)
            d = args.pop('direction', None)
            if hasattr(self._model, 'is_balance_flow'):
                args['balance_flow'] = self._model.is_balance_flow

            parent = args.pop('parent', ParentFragment) or ParentFragment
            if hasattr(self._model, 'flow'):
                the_origin = self._model.flow.origin
                the_id = self._model.flow.entity_id
                direction = self._model.direction
                args['uuid'] = self._model.entity_uuid
            else:
                if f is None:
                    print(self._model.model_dump_json(indent=2))
                    raise MalformedOryxEntity(self.link)
                the_origin = f['origin']
                the_id = f['entity_id']
                direction = d

            if hasattr(self._model, 'parent'):
                parent = self._model.parent or ParentFragment

            try:
                flow = query.cascade(the_origin).get(the_id)  # get locally
            except UnknownOrigin:
                flow = query.get(the_id, origin=the_origin)  # get remotely

            if self.origin != query.origin:
                args['masquerade'] = self.origin

            if hasattr(self._model, 'exchange_values'):
                args['exchange_values'] = self._model.exchange_values

            ref = FragmentRef(self.external_ref, query,
                              flow=flow, direction=direction, parent=parent, **args)

            if hasattr(self._model, 'anchors'):
                ref.anchors(**self._model.anchors)

            self._ref = ref
            return ref

        return super(OryxEntity, self).make_ref(query)


class OryxClient(XdbClient):

    _base_type = OryxEntity

    @property
    def missing(self):
        return self.r.origin_get_many(MissingResource, 'missing')

    def clear_unit_scores(self, lcia_method):
        pass

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

    def _model_to_entity(self, model):
        if model.entity_type == 'fragment':
            ''' check for flow spec '''
            if hasattr(model, 'flow'):
                self.get_or_make(model.flow)
            else:
                if hasattr(model, 'properties') and 'flow' in model.properties:
                    self.get_or_make(FlowEntity(**model.properties['flow']))
                else:
                    model = self._requester.origin_get_one(FragmentEntity, model.origin, 'fragments',
                                                           model.entity_id)
                    self.get_or_make(model.flow)

        ent = super(OryxClient, self)._model_to_entity(model)
        if ent.uuid is not None:
            self._entities[ent.uuid] = ent
        return ent

    def frag(self, string, many=True, strict=False):
        found = None
        for v in self.entities_by_type('fragment'):
            if v.uuid.startswith(string):
                if many or not strict:
                    return v
                else:
                    if found is None:
                        found = v
                    else:
                        raise AmbiguousReference(string)
        if found is None:
            raise FragmentNotFound(string)
        return found


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
        we do with local.qdb). this happens automatically in entity.make_ref() when the query origin doesn't match the
        entity origin

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
        print('I have a theory this tranche of code never gets run %s' % external_ref)
        return self._archive.query.get(external_ref, **kwargs)

    # foreground resource operations-- non-masqueraded
    def fragments(self, **kwargs):
        llargs = {k.lower(): v for k, v in kwargs.items()}
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel, 'fragments', **llargs)]

    def frag(self, string, many=False, **kwargs):
        """
        this just runs locally
        :param string:
        :param many:
        :param kwargs:
        :return:
        """
        return self._archive.frag(string, many=many, **kwargs)

    def frags(self, string, **kwargs):
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel,
                                                                               'frags', string)]

    def knobs(self, search=None, reference=False):
        return [self._archive.get_or_make(k) for k in self._archive.r.get_many(FragmentRefModel,
                                                                               'knobs', search=search,
                                                                               reference=reference)]

    @staticmethod
    def _sc(scenario):
        if scenario is None:
            return None
        elif isinstance(scenario, int):
            return str(scenario)
        elif isinstance(scenario, str):
            return scenario
        elif hasattr(scenario, '__iter__'):
            return ','.join(map(str, scenario))
        raise TypeError(scenario)

    def ev(self, frag, scenario=None, observed=None):
        scenario = self._sc(scenario)
        if scenario is None:
            return self._archive.r.origin_get_one(float, self._o(frag), 'fragments', _ref(frag), 'ev',
                                                  observed=bool(observed))
        return self._archive.r.origin_get_one(float, self._o(frag), 'fragments', _ref(frag), 'ev',
                                              scenario=scenario)

    def new_fragment(self, flow, direction, parent=None, external_ref=None, uuid=None, balance=None,
                     value=None, exchange_value=None, units=None,
                     **kwargs):
        """
        The strategy here is to just POST a fragment entity.
        :param flow:
        :param direction:
        :param parent:
        :param external_ref:
        :param uuid:
        :param balance:
        :param value:
        :param exchange_value: synonym for value
        :param units:
        :param kwargs:
        :return:
        """
        if uuid is None:
            uuid = str(uuid4())
        if external_ref is None:
            entity_id = uuid
        else:
            entity_id = external_ref
        if parent is None:
            direction = comp_dir(direction)
            p = None
            origin = self.origin
        else:
            p = _ref(parent)
            origin = self._o(parent)
        frag = FragmentEntity(origin=origin, entity_id=entity_id, flow=FlowEntity.from_flow(flow), direction=direction,
                              entity_uuid=uuid, is_balance_flow=balance, exchange_values={'0': 1.0}, anchors=dict(),
                              parent=p, properties=kwargs)
        fragments = [self._archive.get_or_make(k) for k in
                     self._archive.r.post_return_many([frag.model_dump()], FragmentRefModel, 'fragments')]
        if len(fragments) > 1:
            logging.warning('Multiple fragments returned!')
        fragment = fragments[0]
        if exchange_value is None:
            if value is not None:
                exchange_value = value
        if exchange_value:
            self.observe(fragment, exchange_value=exchange_value, units=units)
        return fragment

    def post_foreground(self, fg, save_unit_scores=False):
        pydantic_fg = LcForeground.from_foreground_archive(fg.archive, save_unit_scores=save_unit_scores)
        return self._archive.r.post_return_one(pydantic_fg.dict(), OriginCount, 'post_foreground')

    def post_entity_refs(self, entities, **kwargs):
        post_ents = [p if isinstance(p, EntityRef) else EntityRef.from_entity(p) for p in entities]
        return self._archive.r.post_return_one([p.model_dump() for p in post_ents], OriginCount, 'entity_refs')

    def save(self, description=None, author=None, notes=None, major=False):
        if description is None:
            raise ValueError('Foreground release description must be provided')
        release = ForegroundRelease(major=major, description=description, author=author, notes=notes)
        return self._archive.r.post_return_one(release.model_dump(), bool, 'save_foreground')

    def restore(self):
        return self._archive.r.post_return_one(None, bool, 'restore_foreground')

    # Entity operations- masqueraded
    def get_reference(self, key):
        try:
            # !TODO! key will always be an external_ref so _o(key) will fail
            parent = self._archive.r.origin_get_one(FragmentRefModel, self._o(key), _ref(key), 'reference')
        except HTTPError as e:
            if e.args[0] == 400:
                raise ParentFragment
            raise e
        return self._archive.get_or_make(parent)

    def get_fragment(self, fragment):
        """
        detailed version of a fragment
        :param fragment:
        :return:
        """
        return self._archive.r.origin_get_one(FragmentEntity, self._o(fragment), 'fragments', _ref(fragment))

    def child_flows(self, fragment, **kwargs):
        return [self._archive.get_or_make(k) for k in self._archive.r.origin_get_many(FragmentRefModel,
                                                                                      self._o(fragment),
                                                                                      'fragments', _ref(fragment),
                                                                                      'child_flows')]

    def top(self, fragment, **kwargs):
        return self._archive.get_or_make(self._archive.r.origin_get_one(FragmentRefModel,
                                                                        self._o(fragment), _ref(fragment), 'top'))

    def anchors(self, fragment, **kwargs):
        a = self._archive.r.origin_get_one(dict, self._o(fragment), 'fragments', _ref(fragment), 'anchors')
        return {k: Anchor(**v) for k, v in a.items()}

    def scenarios(self, fragment, **kwargs):
        return self._archive.r.origin_get_many(str, self._o(fragment), _ref(fragment),
                                               'scenarios', **kwargs)

    def nodes(self, **kwargs):
        fbs = self._archive.r.get_many(FragmentBranch, 'nodes', **kwargs)
        for fb in fbs:
            self._archive.get_or_make(fb.node)
        return fbs

    def _get_or_make_fragment_flows(self, ffs):
        """
        whoo-ee we love danger
        :param ffs:
        :return:
        """
        for ff in ffs:
            subfrags = [FragmentFlow(**f) for f in ff.subfragments]
            self._get_or_make_fragment_flows(subfrags)
            self._archive.get_or_make(ff.node)

    def traverse(self, fragment, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        ffs = self._archive.r.origin_get_many(FragmentFlow, self._o(fragment), _ref(fragment),
                                              'traverse', scenario=scenario, **kwargs)

        self._get_or_make_fragment_flows(ffs)

        return ffs

    def cutoff_flows(self, fragment, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        ffs = self._archive.r.origin_get_many(FragmentFlow, self._o(fragment), _ref(fragment),
                                              'cutoff_flows', scenario=scenario, **kwargs)

        self._get_or_make_fragment_flows(ffs)

        return ffs

    def activity(self, fragment, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_many(FragmentFlow, self._o(fragment), _ref(fragment),
                                               'activity', scenario=scenario, **kwargs)

    def tree(self, fragment, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_many(FragmentBranch, self._o(fragment), _ref(fragment),
                                               'tree', scenario=scenario, **kwargs)

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, mode=None, **kwargs):
        scenario = self._sc(scenario)
        if mode == 'detailed':
            return self.detailed_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'flat':
            return self.flat_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'stage':
            return self.stage_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        elif mode == 'anchor':
            return self.anchor_lcia(fragment, quantity_ref, scenario=scenario, **kwargs)
        return self._archive.r.origin_get_one(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                              'fragment_lcia',
                                              _ref(quantity_ref), scenario=scenario, **kwargs)

    def detailed_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_one(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                              'detailed_lcia',
                                              _ref(quantity_ref), scenario=scenario, **kwargs)

    def flat_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_one(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                              'lcia',
                                              _ref(quantity_ref), scenario=scenario, **kwargs)

    def stage_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_one(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                              'stage_lcia',
                                              _ref(quantity_ref), scenario=scenario, **kwargs)

    def anchor_lcia(self, fragment, quantity_ref, scenario=None, **kwargs):
        scenario = self._sc(scenario)
        return self._archive.r.origin_get_one(LciaResultModel, self._o(fragment), 'fragments', _ref(fragment),
                                              'anchor_lcia',
                                              _ref(quantity_ref), scenario=scenario, **kwargs)

    def observe(self, fragment, scenario=None, exchange_value=None, units=None, name=None, anchor=None,
                anchor_node=None, anchor_flow=None, descend=None, **kwargs):
        if anchor is None:
            if anchor_node:
                if anchor_flow:
                    anchor_flow = EntityRef.from_entity(anchor_flow)
                if anchor_node.entity_type == 'context':
                    anchor = Anchor(context=anchor_node.as_list(), anchor_flow=anchor_flow)
                else:
                    anchor = Anchor(node=EntityRef.from_entity(anchor_node), anchor_flow=anchor_flow, descend=descend)
        obs = Observation(fragment=EntityRef.from_entity(fragment),
                          scenario=scenario,
                          exchange_value=exchange_value,
                          units=units,
                          name=name,
                          anchor=anchor)
        obs_apply = self._archive.r.origin_post_return_many('observation', obs.model_dump(), Observation, **kwargs)
        # we somehow need to update the local copies of the fragment with the observations
        for o in obs_apply:
            if o.name:
                self._archive.name_fragment(o.fragment, o.name, **kwargs)
            if o.anchor:
                fragment._query.make_term_from_anchor(fragment, o.anchor, o.scenario)
        return obs_apply
