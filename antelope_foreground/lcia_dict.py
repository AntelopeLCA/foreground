from collections import defaultdict
from antelope_core.lcia_results import LciaResult, DuplicateResult


class LciaResults(dict):
    """
    A dict of LciaResult objects, with some useful attachments.  The dict gets added to in the normal way, but
    also keeps track of the keys added in sequence, so that they can be retrieved by numerical index.

    The LciaResults object keys should be quantity links

    only keeping this around because I use it in terminations
    """
    def __init__(self, entity, *args, **kwargs):
        super(LciaResults, self).__init__(*args, **kwargs)
        self.entity = entity
        self._scale = 1.0
        self._indices = []

    def __getitem__(self, item):
        """
        __getitem__ can either be used as a numerical index
        :param item:
        :return:
        """
        try:
            return super(LciaResults, self).__getitem__(item)
        except KeyError:
            try:
                int(item)
                return super(LciaResults, self).__getitem__(self._indices[item])
            except (ValueError, TypeError):
                try:
                    return super(LciaResults, self).__getitem__(next(k for k in self.keys() if k.startswith(item)))
                except StopIteration:
                    return LciaResult(None)  #

    def __setitem__(self, key, value):
        assert isinstance(value, LciaResult)
        value.scale_result(self._scale)
        super(LciaResults, self).__setitem__(key, value)
        if key not in self._indices:
            self._indices.append(key)

    '''
    def add(self, value):
        # TODO: add should cumulate components if LciaResult is already present
        assert isinstance(value, LciaResult)
        self.__setitem__(value.quantity.link, value)
    '''

    def indices(self):
        for i in self._indices:
            yield i

    def to_list(self):
        return [self.__getitem__(k) for k in self._indices]

    def scale(self, factor):
        if factor == self._scale:
            return
        self._scale = factor
        for k in self._indices:
            self[k].scale_result(factor)

    def show(self):
        print('LCIA Results\n%s\n%s' % (self.entity, '-' * 60))
        if self._scale != 1.0:
            print('%60s: %10.4g' % ('scale', self._scale))
        for i, q in enumerate(self._indices):
            r = self[q]
            r.scale_result(self._scale)
            print('[%2d] %.3s  %10.5g %s' % (i, q, r.total(), r.quantity))

    def apply_weighting(self, weights, quantity, **kwargs):
        """
        Create a new LciaResult object containing the weighted sum of entries in the current object.

        We want the resulting LciaResult to still be aggregatable. In order to accomplish this, we need to maintain
        all the individual _LciaScores entities in the weighting inputs, and compute their weighted scores here. Then
        we need to log the weighted scores as the *node weights* and use *unit* values of unit scores, because
        SummaryLciaResults are only allowed to be further aggregated if they have the same unit score.

        This feels a bit hacky and may turn out to be a terrible idea.  But there is a certain harmony in making the
        quantity's unit THE unit for a weighting computation. So I think it will work for now.

        :param weights: a dict mapping quantity UUIDs to numerical weights
        :param quantity: EITHER an LcQuantity OR a string to use as the name of in LcQuantity.new()
        :param kwargs: passed to LciaResult
        :return:
        """
        weighted_result = LciaResult(quantity, **kwargs)

        component_list = dict()  # dict maps keys entities
        component_score = defaultdict(float)  # maps keys to weighted scores
        for method, weight in weights.items():
            try:
                result = self.__getitem__(method)  # an LciaResult
            except KeyError:
                continue
            for comp in result.keys():
                if comp in component_list.keys():
                    if result[comp].entity != component_list[comp]:
                        raise DuplicateResult('Key %s matches different entities:\n%s\n%s' % (comp,
                                                                                              result[comp],
                                                                                              component_list[comp]))
                else:
                    component_list[comp] = result[comp].entity
                component_score[comp] += (weight * result[comp].cumulative_result)

        for comp, ent in component_list.items():
            weighted_result.add_component(comp, entity=ent)
            weighted_result.add_summary(comp, ent, component_score[comp], 1.0)

        return weighted_result

    def clear(self):
        super(LciaResults, self).clear()
        self._indices = []

    def update(self, *args, **kwargs):
        super(LciaResults, self).update(*args, **kwargs)
        self._indices = list(self.keys())


class LciaWeighting(object):
    def __init__(self, quantity, weighting):
        """

        :param quantity: a new LcQuantity to represent the weighting
        :param weighting: a weighting dict as defined in apply_weighting
        """
        self._q = quantity
        self._w = weighting

    def weigh(self, res, **kwargs):
        return res.apply_weighting(self._w, self._q, **kwargs)

    def q(self):
        return self._q.link
