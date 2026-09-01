{# Format chips over the bottom-left of the artwork, opposite the watched tick.
   Three fixed slots rather than one long label: the Python side fills badge.1,
   badge.2 and badge.3 in priority order, so each chip has a fixed position and
   nothing has to be measured or reflowed. Anything below the poster collides
   with the title. #}
{% with chip_w = chip_w|default(52) & chip_h = chip_h|default(22) & chip_gap = chip_gap|default(4) & chip_font = chip_font|default("font10") %}
{% for slot in [1, 2, 3] %}
<control type="group">
    <visible>!String.IsEmpty(ListItem.Property(badge.{{ slot }}))</visible>
    <posx>{{ badge_x + (slot - 1) * (chip_w + chip_gap) }}</posx>
    <posy>{{ badge_y }}</posy>
    <control type="image">
        <posx>0</posx>
        <posy>0</posy>
        <width>{{ chip_w }}</width>
        <height>{{ chip_h|vscale }}</height>
        <texture border="4">script.plex/white-square-rounded.png</texture>
        <colordiffuse>D8000000</colordiffuse>
    </control>
    <control type="label">
        {# same trick the unwatched count uses: oversized font zoomed down, so
           five characters still fit inside a chip this small #}
        <animation effect="zoom" start="70" end="70" time="0" reversible="false" center="auto" condition="true">Conditional</animation>
        <posx>0</posx>
        <posy>0</posy>
        <width>{{ chip_w }}</width>
        <height>{{ chip_h|vscale }}</height>
        <font>{{ chip_font }}</font>
        <align>center</align>
        <aligny>center</aligny>
        <textcolor>FFE5A00D</textcolor>
        <label>$INFO[ListItem.Property(badge.{{ slot }})]</label>
    </control>
</control>
{% endfor %}
{% endwith %}
