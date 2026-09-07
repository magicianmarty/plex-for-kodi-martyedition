{% with ref = itemref|default("ListItem") & bx = bx|default(6) & by = by|default(6) %}
<control type="group">
    <visible>!String.IsEmpty({{ ref }}.Property(badge.dovi))</visible>
    <posx>{{ bx }}</posx>
    <posy>{{ by|vscale }}</posy>
    <width>46</width>
    <height>{{ vscale(26) }}</height>
    <control type="image">
        <texture border="6" colordiffuse="FFE5A00D">script.plex/white-square-rounded.png</texture>
    </control>
    <control type="label">
        <font>font10</font>
        <textcolor>FF000000</textcolor>
        <align>center</align>
        <aligny>center</aligny>
        <label>DV</label>
    </control>
</control>
<control type="group">
    <visible>!String.IsEmpty({{ ref }}.Property(badge.atmos))</visible>
    <posx>{{ bx }}</posx>
    <posy>{{ (by + 32)|vscale }}</posy>
    <width>90</width>
    <height>{{ vscale(26) }}</height>
    <control type="image">
        <texture border="6" colordiffuse="E6101418">script.plex/white-square-rounded.png</texture>
    </control>
    <control type="label">
        <font>font10</font>
        <textcolor>FFE5A00D</textcolor>
        <align>center</align>
        <aligny>center</aligny>
        <label>ATMOS</label>
    </control>
</control>
{% endwith %}
