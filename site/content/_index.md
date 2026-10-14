---
title: jupedsim-network
layout: hextra-home
---

{{< hextra/hero-badge link="https://pypi.org/project/jupedsim-network/" >}}
  <span>Version {{< param "version" >}} · prototype · LGPL-3.0 licence</span>
  {{< icon name="arrow-circle-right" attributes="height=14" >}}
{{< /hextra/hero-badge >}}

<div class="hx-mt-6 hx-mb-6 hx-flex hx-flex-wrap hx-items-center hx-gap-6">
<img src="images/jupedsim-network-logo.png" alt="JuPedSim Network logo" width="120" height="80" style="max-width: 100%; height: auto;" />
{{< hextra/hero-headline >}}
  Network egress model <br class="sm:hx-block hx-hidden" />for fast evacuation-time estimates
{{< /hextra/hero-headline >}}
</div>

<div class="hx-mb-12">
{{< hextra/hero-subtitle >}}
  Rooms, corridors and stairs are nodes with an area; doors and stair&nbsp;<br class="sm:hx-block hx-hidden" />entries are links with a flow capacity. Agents follow relations adapted from the&nbsp;<br class="sm:hx-block hx-hidden" />SFPE hydraulic model, so a ten-storey building runs in about 0.1 s.
{{< /hextra/hero-subtitle >}}
</div>

<div class="hx-mb-6 hx-flex hx-flex-wrap hx-items-center hx-gap-4">
{{< hextra/hero-button text="Get started" link="docs/getting-started/" >}}
{{< hextra/hero-button text="Model description" link="docs/model/" >}}
{{< hextra/hero-button text="Limitations" link="docs/limitations/" >}}
</div>

<div class="content hx-mb-12">
A companion to <a href="https://www.jupedsim.org">JuPedSim</a>. The evacuation time covers pre-movement and movement; detection and alarm count only if added to the pre-movement time. Research software, verified against hand calculations but not validated against experiments. Not intended for regulatory or design use.
</div>

{{< hextra/feature-grid >}}
{{< hextra/feature-card title="Nodes and links" subtitle="Rooms, corridors and stairs are nodes with an area; doors and stair entries are links with a flow capacity." link="docs/model/elements/" >}}
{{< hextra/feature-card title="SFPE-based relations" subtitle="Agents move under relations adapted from the SFPE hydraulic model, updated with a synchronous scheme on every time step." link="docs/model/update-scheme/" >}}
{{< hextra/feature-card title="Fast runs" subtitle="A ten-storey building runs in about 0.1 s, so many scenarios can be screened quickly." link="docs/ten-storey/" >}}
{{< /hextra/feature-grid >}}
