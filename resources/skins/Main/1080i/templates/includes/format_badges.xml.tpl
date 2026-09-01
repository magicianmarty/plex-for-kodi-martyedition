{# Format chips across the top-left of the artwork. The watched tick owns the
   top-right, so the number of chips is capped per view: three fit on a full
   poster, only two on the small ones before they collide with it.
   Three fixed slots rather than one long label: the Python side fills badge.1,
   badge.2 and badge.3 in priority order, so each chip has a fixed position and
   nothing has to be measured or reflowed. Anything below the poster collides
   with the title. #}
{% with chip_w = chip_w|default(52) & chip_h = chip_h|default(22) & chip_gap = chip_gap|default(4) & chip_font = chip_font|default("font10") & chip_slots = chip_slots|default(3) %}
{% for slot in [1, 2, 3] %}
{% if slot <= chip_slots %}
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
        {# The unwatched count's trick, and the reason it widens the control:
           Kodi truncates the text to the control's width *before* the zoom is
           applied, so a chip-width label turns ATMOS into "AT...". Give it room
           to lay the text out, then shrink it into the chip. #}
        <animation effect="zoom" start="70" end="70" time="0" reversible="false" center="auto" condition="true">Conditional</animation>
        <posx>-{{ chip_w }}</posx>
        <posy>0</posy>
        <width>{{ chip_w * 3 }}</width>
        <height>{{ chip_h|vscale }}</height>
        <font>{{ chip_font }}</font>
        <align>center</align>
        <aligny>center</aligny>
        <textcolor>FFE5A00D</textcolor>
        <label>$INFO[ListItem.Property(badge.{{ slot }})]</label>
    </control>
</control>
{% endif %}
{% endfor %}
{% endwith %}
