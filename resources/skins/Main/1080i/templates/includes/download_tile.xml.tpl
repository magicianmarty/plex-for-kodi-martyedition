<control type="group">
    <control type="image">
        <posx>8</posx>
        <posy>0</posy>
        <width>271</width>
        <height>{{ vscale(406) }}</height>
        <aspectratio align="center" aligny="center">scale</aspectratio>
        <texture fallback="$INFO[ListItem.Property(thumb.fallback)]" background="true">$INFO[ListItem.Icon]</texture>
    </control>
    {% if tile_focus %}
    <control type="image">
        <posx>8</posx>
        <posy>0</posy>
        <width>271</width>
        <height>{{ vscale(406) }}</height>
        <texture border="2">script.plex/white-square-rounded.png</texture>
        <colordiffuse>40E5A00D</colordiffuse>
    </control>
    {% endif %}

    <!-- Status band across the foot of the poster: state on the left, how far
         along on the right, over a scrim so it stays readable on any artwork. -->
    <control type="image">
        <posx>8</posx>
        <posy>{{ vscale(330) }}</posy>
        <width>271</width>
        <height>{{ vscale(76) }}</height>
        <texture>script.plex/white-square.png</texture>
        <colordiffuse>C8000000</colordiffuse>
    </control>
    <control type="label">
        <posx>20</posx>
        <posy>{{ vscale(336) }}</posy>
        <width>170</width>
        <height>{{ vscale(30) }}</height>
        <font>font10</font>
        <align>left</align>
        <aligny>center</aligny>
        <textcolor>$INFO[ListItem.Property(state.colour)]</textcolor>
        <label>$INFO[ListItem.Property(state)]</label>
    </control>
    <control type="label">
        <visible>!String.IsEmpty(ListItem.Property(has.progress))</visible>
        <posx>267</posx>
        <posy>{{ vscale(336) }}</posy>
        <width>100</width>
        <height>{{ vscale(30) }}</height>
        <font>font12</font>
        <align>right</align>
        <aligny>center</aligny>
        <textcolor>FFEDEDED</textcolor>
        <label>$INFO[ListItem.Property(percent.display)]</label>
    </control>
    <control type="label">
        <posx>20</posx>
        <posy>{{ vscale(362) }}</posy>
        <width>247</width>
        <height>{{ vscale(26) }}</height>
        <font>font10</font>
        <align>left</align>
        <aligny>center</aligny>
        <textcolor>FF9C9C9C</textcolor>
        <label>$INFO[ListItem.Property(detail)]</label>
    </control>
    <control type="group">
        <visible>!String.IsEmpty(ListItem.Property(has.progress))</visible>
        <control type="image">
            <posx>8</posx>
            <posy>{{ vscale(400) }}</posy>
            <width>271</width>
            <height>{{ vscale(6) }}</height>
            <texture>script.plex/white-square.png</texture>
            <colordiffuse>30FFFFFF</colordiffuse>
        </control>
        <control type="progress">
            <posx>8</posx>
            <posy>{{ vscale(400) }}</posy>
            <width>271</width>
            <height>{{ vscale(6) }}</height>
            <info>ListItem.Property(percent)</info>
            <midtexture colordiffuse="FFE5A00D">script.plex/white-square.png</midtexture>
        </control>
    </control>

    <control type="label">
        <posx>8</posx>
        <posy>{{ vscale(408) }}</posy>
        <width>271</width>
        <height>{{ vscale(30) }}</height>
        <font>font10</font>
        <align>center</align>
        <aligny>center</aligny>
        <textcolor>FFEDEDED</textcolor>
        <label>$INFO[ListItem.Label]</label>
    </control>
</control>
