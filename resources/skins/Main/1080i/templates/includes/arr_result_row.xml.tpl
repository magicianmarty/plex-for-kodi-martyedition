<control type="image">
    <posx>16</posx>
    <posy>{{ vscale(6) }}</posy>
    <width>56</width>
    <height>{{ vscale(76) }}</height>
    <aspectratio align="center" aligny="center">keep</aspectratio>
    <texture fallback="$INFO[ListItem.Property(thumb.fallback)]" background="true">$INFO[ListItem.Icon]</texture>
</control>
<control type="label">
    <posx>92</posx>
    <posy>{{ vscale(8) }}</posy>
    <width>1300</width>
    <height>{{ vscale(36) }}</height>
    <font>font13</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FFEDEDED</textcolor>
    <label>$INFO[ListItem.Label]</label>
</control>
<control type="label">
    <posx>92</posx>
    <posy>{{ vscale(44) }}</posy>
    <width>1300</width>
    <height>{{ vscale(30) }}</height>
    <font>font10</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FF9C9C9C</textcolor>
    <label>$INFO[ListItem.Label2]</label>
</control>
<control type="label">
    <posx>1740</posx>
    <posy>{{ vscale(8) }}</posy>
    <width>300</width>
    <height>{{ vscale(36) }}</height>
    <font>font12</font>
    <align>right</align>
    <aligny>center</aligny>
    <textcolor>$INFO[ListItem.Property(state.colour)]</textcolor>
    <label>$INFO[ListItem.Property(state)]</label>
</control>
