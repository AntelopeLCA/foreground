"""
A foreground archive is an LcArchive that also knows how to access, serialize, and deserialize fragments.
"""
import json
import os
import re
import logging

from typing import Optional

from pydantic import ValidationError

from ..foreground_query import DelayedQuery, QueryIsDelayed, MissingResource
from ..refs.fragment_ref import FragmentRef
from ..implementations import AntelopeForegroundImplementation, AntelopeBasicImplementation
from ..models import ForegroundMetadata, ForegroundRelease, Observation
from ..exceptions import ForegroundNotSafe, BackReference

from antelope import PropertyExists, CatalogRef, EntityNotFound
from antelope_core.archives import BasicArchive, EntityExists, BASIC_ENTITY_TYPES, LD_CONTEXT, ContextCollision
from ..entities.fragments import LcFragment


FOREGROUND_ENTITY_TYPES = BASIC_ENTITY_TYPES + ('fragment', )


class AmbiguousReference(Exception):
    pass


class FragmentNotFound(Exception):
    pass


class FragmentMismatch(Exception):
    pass


class NonLocalEntity(Exception):
    """
    Foregrounds should store only local entities and references to remote entities
    """
    pass


class LcForeground(BasicArchive):
    """
    An LcForeground is defined by being anchored to a physical directory, which is used to serialize the non-fragment
    entities.  Also within this directory is a subdirectory called fragments, which is used to store fragments
    individually as files.

    Fragments are "observations" of foreground systems. A flow is observed to pass from / into some reference entity
    and is terminated (other end of the flow) to x, which can either be None (a cutoff), or an entity ID which is
    dereferenced to a context (=> elementary) or a process (=>intermediate).

    A foreground is then a collection of observations of flows passing through processes.

    Foreground models can be constructed flow by flow (observed from unit process inventories
    """
    _entity_types = FOREGROUND_ENTITY_TYPES
    _ns_uuid_required = None
    _frags_loaded = False

    _observations = None

    def _ref_to_nsuuid(self, key):
        return None

    def _load_entities_json(self, filename):
        with open(filename, 'r') as fp:
            self.load_from_dict(json.load(fp), jsonfile=filename)

    def _ref_to_key(self, key):
        """
        In a foreground, there are three different ways to retrieve an entity.

        (0) by link.  The master key for each entity is its link, which is its key in _entities.

        (1) by uuid.  fg archives have no nsuuid capabilities, but if an entity has a uuid, it can be retrieved by it.

        (2) by name.  Fragments and any other entities native to the foreground archive can also be retrieved by their
        external ref.  Fragments are the only entities that can be *assigned* a name after creation.  [for this reason,
        Fragments MUST have UUIDs to be used for hashing]
        [Note: flows can also be named but their name is not their external_ref]

         * _ref_to_key transmits the user's heterogeneous input into a valid key to self._entities, or None
           - if the key is already a known link, it's easy
           - if the key is a custom name, it's almost as easy
           - if the key CONTAINS a uuid known to the db, then a link for an entity with that UUID is
              NONDETERMINISTICALLY returned
         * __getitem__ uses _ref_to_key to translate the users input into a key

        For the thorns around renaming fragments, see self.name_fragment() below

        :param key:
        :return:
        """
        if key in self._entities:
            return key
        elif key in self._ext_ref_mapping:
            return self._ext_ref_mapping[key]
        else:
            uid = self._ref_to_uuid(key)
            if uid in self._entities:
                return self._entities[uid]
        return None

    def _add_ext_ref_mapping(self, entity):
        if entity.external_ref in self._ext_ref_mapping:
            if entity == self[entity.external_ref]:
                return  # skip it
            raise EntityExists('External Ref %s already refers to %s' % (entity.external_ref, self[entity.external_ref]))
        self._ext_ref_mapping[entity.external_ref] = entity.link

    def __getitem__(self, item):
        """
        Note: this user-friendliness check adds 20% to the execution time of getitem-- so avoid it if possible
        (use _get_entity directly -- especially now that upstream is now deprecated)
        (note that _get_entity does not get contexts)

        :param item:
        :return:
        """
        if hasattr(item, 'link'):
            item = item.link
        entity = super(BasicArchive, self).__getitem__(item)
        if entity:
            if entity.link in self._unresolved and self._catalog is not None:
                return self._replace_unresolved(entity)
        return entity

    def _replace_unresolved(self, entity):
        # try to find a new one:
        new = self.catalog_ref(entity.origin, entity.external_ref, entity_type=entity.entity_type)
        if not new.resolved:
            return entity  # nothing to do
        ks = [k for k, v in self._entities.items() if v is entity]
        self._unresolved.remove(entity.link)
        for k in ks:
            self._entities[k] = new

        if entity.link != new.link:
            self._ext_ref_mapping[entity.external_ref] = new.link
        return new

    @property
    def _archive_file(self):
        return os.path.join(self.source, 'entities.json')

    @property
    def _metadata_file(self):
        return os.path.join(self.source, 'metadata.json')

    @property
    def _fragment_dir(self):
        return os.path.join(self.source, 'fragments')

    def __init__(self, fg_path, catalog=None, debug_load_fragments=False, **kwargs):
        """

        :param fg_path:
        :param catalog: A foreground archive requires a catalog to deserialize saved fragments. If None, archive will
        still initialize (and will even be able to save fragments) but non-locally terminated fragments will fail.
        :param ns_uuid: Foreground archives may not use ns_uuids, so any namespace uuid provided will be ignored.
        :param kwargs:
        """
        if catalog is not None:
            kwargs['term_manager'] = kwargs.pop('term_manager', catalog.lcia_engine)
        super(LcForeground, self).__init__(fg_path, **kwargs)
        self._catalog = catalog
        self._ext_ref_mapping = dict()

        self._observations = []

        self._metadata = None

        # self._delayed_refs = []
        self._unresolved = set()

        if debug_load_fragments:
            print('%s: FRAGMENTS NOT LOADED' % self.ref)
            self._frags_loaded = True
        self.load_all()

    def observations(self, fresh=True):
        if fresh:
            for obs in self._observations:
                yield obs
        else:
            for frag in self.fragments():
                for obs in frag.observations():
                    yield obs

    @property
    def metadata(self):
        return self._metadata

    def catalog_ref(self, origin, external_ref, entity_type=None, **kwargs):
        """

        :param origin:
        :param external_ref:
        :param entity_type:
        :param kwargs:
        :return:
        """
        '''#this is totally immaterial
        if entity_type == 'term':
            if origin in self._catalog.foregrounds:
                entity_type = 'fragment'
            else:
                entity_type = 'process'
        '''
        if origin in self.catalog_names or origin == 'foreground':
            entity = self.get(external_ref)
            if entity is None:
                print('{%s} local entity %s/%s not found' % (self.ref, origin, external_ref))
                return CatalogRef(origin, external_ref, entity_type=entity_type, **kwargs)
            return entity
        try:
            return self._catalog.internal_ref(self.ref, origin, external_ref)
        except (ForegroundNotSafe, MissingResource, BackReference):
            print('{%s} Creating delayed ref %s/%s [%s]' % (self.ref, origin, external_ref, entity_type))
            dq = DelayedQuery(origin, self._catalog, self.ref)
            if entity_type == 'fragment':
                return FragmentRef(external_ref, dq, **kwargs)
            self._counter['delayed'] += 1
            return CatalogRef.from_query(external_ref, query=dq, etype=entity_type, **kwargs)
        except EntityNotFound:
            print('{%s} entity %s/%s not found' % (self.ref, origin, external_ref))
            return CatalogRef(origin, external_ref, entity_type=entity_type, **kwargs)

    @property
    def delayed(self):
        return self._counter['delayed']

    @property
    def unresolved(self):
        return list(self._unresolved)

    def catalog_query(self, origin, **kwargs):
        return self._catalog.query(origin, **kwargs)

    def _fetch(self, entity, **kwargs):
        return self.__getitem__(entity)

    def _load_all(self):
        if os.path.exists(self._archive_file):
            self._load_entities_json(self._archive_file)
        if os.path.exists(self._metadata_file):
            try:
                with open(self._metadata_file) as fp:
                    self._metadata = ForegroundMetadata(**json.load(fp))
            except (ValidationError, json.JSONDecodeError):
                self._metadata = ForegroundMetadata(version_major=-1, version_minor=-1,
                                                    dataSource=self.source,
                                                    description='failed to load',
                                                    author=self._metadata_file)
        else:
            self._metadata = ForegroundMetadata(version_major=0, version_minor=0,
                                                dataSource=self.source,
                                                description='LcForeground',
                                                author='Antelope')
        self._iface_check_fragments()

    def _iface_check_fragments(self):
        if self._frags_loaded is False:
            self._load_fragments()
            self.check_counter('fragment')
            self._frags_loaded = True

    def make_interface(self, iface):

        if iface == 'foreground':
            self._iface_check_fragments()
            return AntelopeForegroundImplementation(self)
        elif iface == 'basic':
            return AntelopeBasicImplementation(self)
        else:
            return super(LcForeground, self).make_interface(iface)

    def set_origin(self, origin):
        super(LcForeground, self).set_origin(origin)
        for k in self.entities_by_type('fragment'):
            k._origin = origin

    def _flow_ref_from_json(self, e, external_ref):
        origin = e.pop('origin')
        r_q = e.pop('referenceQuantity')  # quantity must have been loaded
        ref_q = self.tm.get_canonical(r_q)
        if ref_q is None:
            e['origin'] = origin
            e['referenceQuantity'] = r_q
            print(e)
            print('XXXXXX EntityNotFound %s' % r_q)
            raise EntityNotFound
        ref = self.catalog_ref(origin, external_ref, entity_type='flow', reference_entity=ref_q, **e)
        if not ref.resolved and self._frags_loaded:  # not found
            try:
                ref_q = self._catalog.get_canonical(r_q)
                name = e.pop('Name', None) or 'unnamed flow %s' % origin
                ref = self.make_interface('foreground').add_or_retrieve(external_ref, ref_q, name, **e)
            except EntityNotFound:
                pass
        return ref

    def _make_entity(self, e, etype, ext_ref):
        if e['origin'] != self.ref and e['origin'] not in self.catalog_names:
            if etype == 'flow':
                return self._flow_ref_from_json(e, ext_ref)
            elif etype == 'quantity':
                try:
                    return self.tm.get_canonical(ext_ref)
                except EntityNotFound:
                    unit = e.pop('referenceUnit', None)
                    return self.catalog_ref(e.pop('origin'), ext_ref, entity_type='quantity', reference_entity=unit, **e)
        e.pop('origin', None)  # just go ahead and domesticate anything we make as an entity
        return super(LcForeground, self)._make_entity(e, etype, ext_ref)

    def _ensure_valid_refs(self, entity):
        """
        we don't need to do so much error checking in the foreground
        :param entity:
        :return:
        """
        if self.tm.is_context(entity.external_ref):
            raise ContextCollision('Entity external_ref %s is already known as a context identifier' %
                                   entity.external_ref)
        if hasattr(entity, 'uuid'):
            if entity.uuid is None:
                uu = self._ref_to_uuid(entity.external_ref)
                if uu is not None:
                    entity.uuid = uu

    def add(self, entity):
        """
        Reimplement base add to (1) use link instead of external_ref, (2) merge instead of raising a key error.
        not sure we really want/need to do the merge thing- we will find out
        :param entity:
        :return:
        """
        if entity.origin is None:
            entity.origin = self.ref  # have to do this now in order to have the link properly defined
        if entity.is_entity:
            if entity.origin != self.ref:
                if entity.origin not in self.catalog_names:
                    # TODO: Alert! entity properties are not preserved in the local ref
                    entity = self.catalog_ref(entity.origin, entity.external_ref, entity_type=entity.entity_type)
            elif entity.entity_type == 'quantity':
                q_ref = entity.make_ref(self.query)
                self._catalog.register_entity_ref(q_ref)

            # for p in entity.properties:
            #     enew[p] = entity[p]  ...
        try:
            self._add(entity, entity.link)
            if not entity.is_entity and not entity.resolved:
                self._unresolved.add(entity.link)
        except EntityExists:
            if entity is self[entity.link]:
                pass
            elif entity.entity_type == 'fragment' and entity.external_ref != entity.uuid:
                raise ValueError('Name is already taken: %s' % entity.external_ref)
            else:
                # merge incoming entity's properties with existing entity
                current = self[entity.link]
                current.merge(entity)

        if hasattr(entity, 'uuid') and entity.uuid is not None:
            self._entities[entity.uuid] = entity

        if entity.origin == self.ref and entity.external_ref != entity.uuid:
            self._add_ext_ref_mapping(entity)

        # it's up to the other foregrounds (local or not) to add their own quantities to the TM
        if entity.entity_type == 'quantity':
            if entity.origin != self.ref and entity.origin in self._catalog.foregrounds:
                # do not add to tm
                return

        try:
            self._add_to_tm(entity)  # , merge_strategy='distinct')  # DWR!!! need to
        except QueryIsDelayed:
            pass

    def _add_children(self, entity):
        if entity.entity_type == 'fragment':
            self.add_entity_and_children(entity.flow)
            for c in entity.child_flows:
                self.add_entity_and_children(c)
        else:
            super(LcForeground, self)._add_children(entity)

    def _rename_mechanics(self, frag, oldname):
        """
        This function updates all the various mappings between a fragment and its references,
        EXCEPT the ext_ref_mapping which is left to outside code because of complexities with sequencing

        This can surely be simplified (currently, renaming a fragment requires calling this twice) but not today.

        :param frag:
        :param oldname:
        :return:
        """
        self._entities[frag.link] = self._entities.pop(oldname)
        self._ents_by_type['fragment'].remove(oldname)
        self._ents_by_type['fragment'].add(frag.link)

    def _dename_fragment(self, prior):
        name = prior.external_ref
        if name == prior.uuid:
            return  # nothing to do
        print('removing name from fragment %s to %s' % (name, prior.uuid))
        priorlink = prior.link
        prior.de_name()
        self._ext_ref_mapping.pop(name)

        self._rename_mechanics(prior, priorlink)
        assert self._ref_to_key(name) is None
        obs = Observation.dename(prior)
        self._observations.append(obs)
        return obs

    def name_fragment(self, frag, name, auto=None, force=None):
        """
        This function is complicated because we have so many dicts:
         _entities maps link to entity
         _ext_ref_mapping maps custom name to link
         _ents_by_type keeps a set of links by entity type

        So, when we name a fragment, we want to do the following:
         - ensure the fragment is properly in the _entities dict
         - ensure the name is not already taken
         - set the fragment entity's name
         * pop the old link and replace its object with the new link in _entities
         * remove the old link and replace it with the new link in ents_by_type['fragment']
         * add the name with the new link to the ext_ref_mapping
        :param frag:
        :param name:
        :param auto: if True, if name is taken, apply an auto-incrementing numeric suffix until a free name is found
        :param force: if True, if name is taken, de-name the prior fragment and assign the name to the current one.
         This requires:
           - first de-naming the prior fragment,
           - then swapping its _entities entry
           - then swapping its _ents_by_type entry
           - then removing its duplicate ext_ref_mapping
           = then proceeding to normally rename the new frag
         If both auto and force are specified, auto takes precedence.
        :return: returns the assigned name
        """
        if frag.external_ref == name:
            return  # nothing to do-- fragment is already assigned that name
        if name.find('/') >= 0:
            raise ValueError('"%s": Fragment name cannot include forward slash' % name)
        current = self[frag.link]
        if current is not frag:
            if current is None:
                raise FragmentNotFound(frag)
            raise FragmentMismatch('%s\n%s' % (current, frag))
        if self._ref_to_key(name) is not None:
            if auto:
                inc = 0
                newname = '%s %02d' % (name, inc)
                while self._ref_to_key(newname) is not None:
                    inc += 1
                    newname = '%s %02d' % (name, inc)
                name = newname
            elif force:
                prior = self._entities[self._ref_to_key(name)]
                assert prior.external_ref == name
                self._dename_fragment(prior)
            else:
                raise ValueError('Name is already taken: "%s"' % name)
        oldname = frag.link
        try:
            frag.external_ref = name  # will raise PropertyExists if already set
        except PropertyExists:  # don't need force to rename a nonconflicting fragment
            self._dename_fragment(frag)
            oldname = frag.link
            frag.external_ref = name

        self._add_ext_ref_mapping(frag)
        self._rename_mechanics(frag, oldname)
        assert self._ref_to_key(name) == frag.link
        obs = Observation.from_name(frag)
        self._observations.append(obs)

        return obs

    def observe_ev(self, fragment, scenario=None, value=None, units=None):
        if value is not None:
            fragment.observe(scenario=scenario, value=value, units=units)
            obs = Observation.ev(fragment, scenario, value, units)
            self._observations.append(obs)
        elif scenario is None and fragment.observed_ev == 0:
            # If we are observing a fragment with no scenario and no observed ev, we simply apply the cached ev
            fragment.observe(value=fragment.cached_ev)
            obs = Observation.ev(fragment, scenario, fragment.cached_ev)
            self._observations.append(obs)
        else:
            fragment.set_exchange_value(scenario, None)
            obs = Observation.ev(fragment, scenario, None)
        return obs

    def observe_anchor(self, fragment, scenario, anchor_target, anchor_flow, descend=None):
        if anchor_target.entity_type != 'context':
            # adds dependency and turns models into entities (idempotent)
            anchor_target = self._catalog.internal_ref(self.ref, anchor_target.origin, anchor_target.external_ref)
        term = fragment.terminate(anchor_target, scenario=scenario, term_flow=anchor_flow, descend=descend)
        anchor = term.to_anchor()
        obs = Observation.from_anchor(fragment, scenario, anchor)  # and back into model
        self._observations.append(obs)
        return obs

    '''
    Save and load the archive
    '''
    def _do_load(self, fragments):
        for f in fragments:
            frag = LcFragment.from_json(self, f)
            # if frag.external_ref != frag.uuid:  # don't need this anymore- auto-added for entities with self.ref
            #     self._add_ext_ref_mapping(frag)
            self.add(frag)

        self._frags_loaded = True  # they all now exist and should not be loaded again

        for f in fragments:
            frag = self[f['entityId']]
            try:
                frag.finish_json_load(self, f)
            except AttributeError:
                print(f)
                raise

    def _load_fragments(self):
        """
        This must be done in two steps, since fragments refer to other fragments in their definition.
        First step: create all fragments.
        Second step: set reference entities and terminations
        :return:
        """
        fragments = []
        if not os.path.exists(self._fragment_dir):
            if self._catalog and self._catalog.test:
                return
            os.makedirs(self._fragment_dir)
        for file in os.listdir(self._fragment_dir):
            if os.path.isdir(os.path.join(self._fragment_dir, file)):
                continue
            with open(os.path.join(self._fragment_dir, file), 'r') as fp:
                j = json.load(fp)

            fragments.extend(j['fragments'])
        self._do_load(fragments)

    def _recurse_frags(self, frag):
        frags = [frag]
        for x in sorted(frag.child_flows, key=lambda z: z.uuid):
            frags.extend(self._recurse_frags(x))
        return frags

    def _map_frag_org(self, migration_map, json_block):
        """
        update a json block according to the map of origin migrations.

        :param migration_map:
        :param json_block: must contain 'origin'
        :return:
        """
        if isinstance(json_block, str):
            return
        o = json_block.get('origin')
        if o in migration_map:
            new_org = migration_map[o]
            if new_org == self.ref or new_org is None:
                new_org = 'foreground'
            json_block['origin'] = new_org

    def save_fragments(self, save_unit_scores=False, migration_map=None):
        current_files = os.listdir(self._fragment_dir)
        for r in self._fragments():
            frags = [t.serialize(save_unit_scores=save_unit_scores) for t in self._recurse_frags(r)]
            if migration_map:

                for frag in frags:
                    # map flow origin
                    self._map_frag_org(migration_map, frag['flow'])

                    # map each term's origin
                    for k, term in frag['terminations'].items():
                        self._map_frag_org(migration_map, term)

                        # and termFlow if it exists
                        if 'termFlow' in term:
                            self._map_frag_org(migration_map, term['termFlow'])

            fname = r.uuid + '.json'
            if fname in current_files:
                current_files.remove(fname)
            tgt_file = os.path.join(self._fragment_dir, fname)
            with open(tgt_file, 'w') as fp:
                json.dump({'fragments': frags}, fp, indent=2, sort_keys=True)
        for leftover in current_files:
            if not os.path.isdir(os.path.join(self._fragment_dir, leftover)):
                print('deleting %s' % leftover)
                os.remove(os.path.join(self._fragment_dir, leftover))

    def save_metadata(self):
        if not os.path.isdir(self.source):
            if self._catalog and self._catalog.test:
                return
            os.makedirs(self.source)

        with open(self._metadata_file, 'w') as fp:
            json.dump(self._metadata.model_dump(), fp, indent=2)

    def migrate(self, new_source, migration_map, save_unit_scores=False):
        """
        Migrates the foreground to a new location with a new ref.  Removes the existing origin from all entities.
        This operates by changing origins in the serialized file
        :param new_source: name of directory to save to
        :param migration_map: a dict of current origins to new origins. must at least contain {current ref: new ref}
        :param save_unit_scores: passed on to save
        :return:
        """
        old_ref = self.ref
        new_source = os.path.abspath(new_source)
        new_ref = migration_map[old_ref]
        self._set_source(new_ref, new_source)
        self.set_origin(new_ref)

        self.save(save_unit_scores=save_unit_scores, migration_map=migration_map)

    def save(self, save_unit_scores=False, migration_map=None):
        if not os.path.isdir(self.source):
            if self._catalog and self._catalog.test:
                logging.error('Cannot save new foregrounds during tester operation')
                return False
            os.makedirs(self.source)

        self.write_to_file(self._archive_file, gzip=False, characterizations=True, values=True,
                           migration_map=migration_map)

        self.save_metadata()

        if not os.path.isdir(self._fragment_dir):
            os.makedirs(self._fragment_dir)
        self.save_fragments(save_unit_scores=save_unit_scores, migration_map=migration_map)
        return True

    def serialize(self, characterizations=False, values=False, domesticate=False, migration_map=None):
        """
        Serialize flows and quantities.  If characterizations==True, also save Term Manager content
        (characterizations, contexts, flowables)

        :param characterizations:
        :param values:
        :param domesticate: [False] if True, omit entities' origins so that they will appear to be from the new archive
         upon serialization.
         If 'domesticate' is a string, entities whose origin matches the string are domesticated.  This is also applied
         to TermManager content.
        :param migration_map:
        :return:
        """
        if migration_map is None:
            return super(LcForeground, self).serialize(characterizations=characterizations, values=values,
                                                       domesticate=domesticate)

        # first, add synonyms
        def _add_syn(_ent):
            if _ent.origin in migration_map:
                _tgt_org = migration_map[_ent.origin]
                _new_link = '%s/%s' % (_tgt_org, _ent.external_ref)
                self.tm.add_synonym(_ent.link, _new_link)

        for f in self.entities_by_type('flow'):
            _add_syn(f)
        for q in self.entities_by_type('quantity'):
            _add_syn(q)

        j = super(BasicArchive, self).serialize()
        j['@context'] = LD_CONTEXT

        j['flows'] = sorted([f.serialize(domesticate=domesticate, drop_fields=self._drop_fields['flow'])
                             for f in self.entities_by_type('flow')],
                            key=lambda x: x['externalId'])

        for flow in j['flows']:
            if flow['origin'] in migration_map:
                tgt_org = migration_map[flow['origin']]
                if tgt_org == self.ref:
                    flow.pop('origin')  # domesticate
                else:
                    flow['origin'] = tgt_org  # migrate

        if characterizations:
            try:
                local = next(k for k, v in migration_map.items() if v == self.ref)
            except StopIteration:
                local = self.ref

            j['termManager'], qqs, rqs = self.tm.serialize(local, values=values)
            # we need to add all the quantities that are mentioned in our characterizations
            for f in qqs:
                if self[f] is None:
                    self.add(self.tm.get_canonical(f))
            for f in rqs:
                if self[f] is None:
                    self.add(self.tm.get_canonical(f))

        j['quantities'] = self._serialize_quantities(domesticate=domesticate)
        for quantity in j['quantities']:
            if quantity['origin'] in migration_map:
                tgt_org = migration_map[quantity['origin']]
                if tgt_org == self.ref:
                    quantity.pop('origin')  # domesticate
                else:
                    quantity['origin'] = tgt_org  # migrate

        return j

    def update_metadata(self, release: Optional[ForegroundRelease] = None, bump_version=True):
        """
        update foreground metadata with release info (default is to bump the version number). also writes the
        metadata file.
        Here we assume the ref has NOT been decorated with the semantic version. add logic to prevent this if
        bad shit starts happening
        :param bump_version: [True] whether to bump the revision
        :param release: ForegroundRelease applied to the metadata
        :return: the path to the zipfile
        """

        # update metadata
        if release is None:
            release = ForegroundRelease(description='no info')

        if bump_version:
            if release.major:
                self.metadata.version_major += 1
                self.metadata.version_minor = 0
            else:
                self.metadata.version_minor += 1

        # we do in fact want to update these fields even if they are None
        self.metadata.release_notes = release.notes
        self.metadata.author = release.author
        self.metadata.description = release.description

        self.save_metadata()

    def clear_unit_scores(self, lcia_method=None):
        logging.info('Clearing unit scores in %s for %s' % (self.ref, lcia_method))
        for f in self.entities_by_type('fragment'):
            for s, t in f.terminations():
                if lcia_method is None:
                    t.clear_score_cache()
                else:
                    t.reset_score(lcia_method)
    '''
    Retrieve + display fragments
    '''
    def _fragments(self, background=None, **kwargs):
        for f in self.search('fragment', **kwargs):
            if f.reference_entity is None:
                if background is None or f.is_background == background:
                    yield f

    def _show_frag_children(self, frag, level=0, show=False):
        level += 1
        for k in frag.child_flows:
            if show:
                print('%s%s' % ('  ' * level, k))
            else:
                yield k
            for j in self._show_frag_children(k, level, show=show):
                yield j

    def fragments(self, *args, show_all=False, background=None, show=False, **kwargs):
        """
        :param : optional first param is filter string-- note: filters only on reference fragments!
        :param show_all: show child fragments as well as reference fragments
        :param background: [None] if True or False, show fragments whose background status is as specified
        :param show: [False] if true, print the fragments instead of returning them
        :param kwargs: search parameters
        :return:
        """
        for f in sorted([x for x in self._fragments(background=background, **kwargs)], key=lambda x: x.is_background):
            if len(args) != 0:
                if not bool(re.search(args[0], str(f), flags=re.IGNORECASE)):
                    continue
            if show:
                print('%s' % f)
                if show_all:
                    self._show_frag_children(f, show=show)
            else:
                yield f
                if show_all:
                    for k in self._show_frag_children(f):
                        yield k

    def fragments_with_flow(self, flow, match=False):
        for k in self.entities_by_type('fragment'):
            if match:
                if k.flow.match(flow):
                    yield k
            else:
                if k.flow == flow:
                    yield k

    def frag(self, string, many=False, strict=True):
        """
        strict=True is slow
        Works as an iterator. If nothing is found, raises StopIteration. If multiple hits are found and strict is set,
        raises Ambiguous Reference.
        :param string:
        :param many: [False] if true, generate
        :param strict: [True] synonym for not many
        :return:
        """
        if strict and not many:
            k = [f for f in self.fragments(show_all=True) if f.uuid.startswith(string.lower())]
            if len(k) > 1:
                for i in k:
                    print('%s' % i)
                raise AmbiguousReference(string)
            try:
                return k[0]
            except IndexError:
                raise FragmentNotFound(string)
        else:
            return self.frags(string)

    def frags(self, string):
        for f in self.fragments(show_all=True):
            if f.uuid.startswith(string.lower()):
                yield f

    def draw(self, string, **kwargs):
        if not isinstance(string, LcFragment):
            string = self.frag(string)
        string.show_tree(**kwargs)

    '''
    Utilities for finding terminated fragments and deleting fragments
    '''
    def delete_fragment(self, frag):
        """
        Need to purge the fragment from:
         _entities
         _ents_by_type
         _ext_ref_mapping
         _frags_with_flow
        and correct _counter.
        The fragment is not destroyed- and can be re-added. Deleting child fragments is left to interface code (why?)
        :param frag:
        :return:
        """
        if frag.origin != self.ref:
            raise FragmentMismatch('Fragment belongs to another foreground!')
        if frag.reference_entity is not None:
            frag.unset_parent()
        self._entities.pop(frag.link)
        self._ents_by_type['fragment'].remove(frag.link)
        self._counter['fragment'] -= 1
        if self._entities[frag.uuid] is frag:
            self._entities.pop(frag.uuid)
        self._ext_ref_mapping.pop(frag.external_ref, None)

    def _del_f(self, f):
        print('Deleting %s' % f)
        del self._entities[f.uuid]

    def del_orphans(self, for_real=False):
        """
        self is a foreground archive -- delete
        """
        for f in self._fragments(background=True):
            if f.reference_entity is not None:
                continue
            try:
                next(self._find_links(f))
                print('Found a link for %s' % f)
            except StopIteration:
                print('### Found orphan %s' % f)
                if for_real:
                    self._del_f(f)

    def _find_links(self, frag):
        for i in self.fragments(show_all=True):
            for s, t in i.terminations():
                if t.term_node is frag:
                    yield t

    def linked_terms(self, frag):
        """
        returns a list of terminations that match the input.
        :param frag:
        :return:
        """
        return [f for f in self._find_links(frag)]
