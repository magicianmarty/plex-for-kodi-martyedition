<control type="image">
    <posx>18</posx>
    <posy>{{ vscale(8) }}</posy>
    <width>62</width>
    <height>{{ vscale(76) }}</height>
    <aspectratio align="center" aligny="center">keep</aspectratio>
    <texture fallback="$INFO[ListItem.Property(thumb.fallback)]" background="true">$INFO[ListItem.Icon]</texture>
</control>
<control type="label">
    <posx>102</posx>
    <posy>{{ vscale(8) }}</posy>
    <width>1340</width>
    <height>{{ vscale(34) }}</height>
    <font>font13</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FFEDEDED</textcolor>
    <label>$INFO[ListItem.Label]</label>
</control>
<control type="label">
    <posx>102</posx>
    <posy>{{ vscale(40) }}</posy>
    <width>1340</width>
    <height>{{ vscale(28) }}</height>
    <font>font10</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FF9C9C9C</textcolor>
    <label>$INFO[ListItem.Label2]$INFO[ListItem.Property(message),  ·  ,]</label>
</control>

<!-- Only for things actually moving: a full-width bar under a queued item
     reads as "stuck at zero". -->
<control type="group">
    <visible>!String.IsEmpty(ListItem.Property(has.progress))</visible>
    <control type="image">
        <posx>102</posx>
        <posy>{{ vscale(72) }}</posy>
        <width>1340</width>
        <height>{{ vscale(6) }}</height>
        <texture border="2">script.plex/white-square-rounded.png</texture>
        <colordiffuse>28FFFFFF</colordiffuse>
    </control>
    <control type="progress">
        <posx>102</posx>
        <posy>{{ vscale(72) }}</posy>
        <width>1340</width>
        <height>{{ vscale(6) }}</height>
        <info>ListItem.Property(percent)</info>
        <midtexture colordiffuse="FFE5A00D" border="2">script.plex/white-square-rounded.png</midtexture>
    </control>
</control>

<control type="label">
    <posx>1700</posx>
    <posy>{{ vscale(8) }}</posy>
    <width>260</width>
    <height>{{ vscale(34) }}</height>
    <font>font12</font>
    <align>right</align>
    <aligny>center</aligny>
    <textcolor>$INFO[ListItem.Property(state.colour)]</textcolor>
    <label>$INFO[ListItem.Property(state)]</label>
</control>
<control type="label">
    <posx>1700</posx>
    <posy>{{ vscale(40) }}</posy>
    <width>260</width>
    <height>{{ vscale(28) }}</height>
    <font>font10</font>
    <align>right</align>
    <aligny>center</aligny>
    <textcolor>FF9C9C9C</textcolor>
    <label>$INFO[ListItem.Property(detail)]</label>
</control>
