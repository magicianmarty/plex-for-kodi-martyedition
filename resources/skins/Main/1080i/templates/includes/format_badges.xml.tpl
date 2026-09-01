<!-- Format badges. One label rather than per-format images: it needs no assets,
     scales with the font, and reads at a distance, which is the whole point of
     a badge. Sits over the bottom of the poster where artwork is usually
     darkest and least interesting. -->
<control type="group">
    <visible>!String.IsEmpty(ListItem.Property(badges))</visible>
    <posx>{{ badge_x }}</posx>
    <posy>{{ badge_y }}</posy>
    <control type="image">
        <posx>0</posx>
        <posy>0</posy>
        <width>{{ badge_w }}</width>
        <height>{{ badge_h }}</height>
        <texture border="6">script.plex/white-square-rounded.png</texture>
        <colordiffuse>C0000000</colordiffuse>
    </control>
    <control type="label">
        <posx>0</posx>
        <posy>0</posy>
        <width>{{ badge_w }}</width>
        <height>{{ badge_h }}</height>
        <font>{{ badge_font }}</font>
        <align>center</align>
        <aligny>center</aligny>
        <textcolor>FFE5A00D</textcolor>
        <label>$INFO[ListItem.Property(badges)]</label>
    </control>
</control>
