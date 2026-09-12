"""The Sharadar production runtime foundations (ADR-0036 / ADR-0037).

The third vendor-scoped package, beside the provider adapter and the private
qualification package. ADR-0036 names Sharadar as the production provider whose
credential, prefixes and datasets these contracts bind, so the vendor name lives
here and nowhere else in the production runtime.

Module map, in the order a run consults them:

- :mod:`vocabulary` -- the two actors and every compiled constant per actor;
- :mod:`bindings` -- the two runtime-binding contracts and their two loaders;
- :mod:`identity` -- the human, launcher and task identity shapes, and the gate;
- :mod:`keys` -- the disjoint production Bronze key builders (ADR-0037);
- :mod:`locator` -- the production run locator and its four validation clauses;
- :mod:`inputs` -- the acquisition and build input contracts;
- :mod:`release` -- the placement-release contract and its exact binding;
- :mod:`metadata` -- the task metadata v4 self-check;
- :mod:`barrier` -- the bounded release barrier;
- :mod:`launcher` -- the launch tool's adapter-driven sequence;
- :mod:`runner` -- the task-side and human-side bootstrap sequences;
- :mod:`outcomes` -- the closed outcome vocabularies and integer counts;
- :mod:`plan`, :mod:`identities`, :mod:`processing` -- the offline acquisition
  processing path (ADR-0038 reservation, provider through an injected adapter,
  ADR-0037 publication, the locator last);
- :mod:`build_inputs`, :mod:`silver`, :mod:`sessions`, :mod:`availability`,
  :mod:`universe`, :mod:`gold`, :mod:`build_manifest`, :mod:`build_processing` --
  the offline research-build processing path (verified inputs, Silver, bounds,
  membership, Gold and quality, the manifest last; proposed ADR-0039 / ADR-0040).
"""
