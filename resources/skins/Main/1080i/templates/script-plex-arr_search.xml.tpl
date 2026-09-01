{% extends "default.xml.tpl" %}
{% block headers %}<defaultcontrol>650</defaultcontrol>{% endblock %}
{% block topleft_add %}
<control type="label">
    <width max="500">auto</width>
    <height>{{ vscale(40) }}</height>
    <font>font12</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FFFFFFFF</textcolor>
    <label>[UPPERCASE]$ADDON[script.plexmod 35094][/UPPERCASE]</label>
</control>
{% endblock %}
{% block content %}
<control type="group">
    <posx>0</posx>
    <posy>{{ vscale(150) }}</posy>

    <control type="image">
        <posx>70</posx>
        <posy>0</posy>
        <width>760</width>
        <height>{{ vscale(64) }}</height>
        <texture border="6">script.plex/white-square-rounded.png</texture>
        <colordiffuse>28FFFFFF</colordiffuse>
    </control>
    <control type="edit" id="650">
        <posx>70</posx>
        <posy>0</posy>
        <width>760</width>
        <height>{{ vscale(64) }}</height>
        <align>left</align>
        <aligny>center</aligny>
        <ondown>101</ondown>
        <onright>101</onright>
        <textcolor>00000000</textcolor>
        <label> </label>
        <hinttext> </hinttext>
        <font>font13</font>
        <textoffsetx>24</textoffsetx>
        <texturefocus border="10">script.plex/home/selected.png</texturefocus>
        <texturenofocus>-</texturenofocus>
        <pulseonselect>no</pulseonselect>
    </control>
    <!-- SafeControlEdit mirrors what has been typed into this label; the edit
         control itself draws nothing, which is how PM4K's own search works. -->
    <control type="label" id="651">
        <scroll>false</scroll>
        <posx>94</posx>
        <posy>0</posy>
        <width>720</width>
        <height>{{ vscale(64) }}</height>
        <align>left</align>
        <aligny>center</aligny>
        <font>font13</font>
        <textcolor>FFEDEDED</textcolor>
        <label></label>
    </control>

    <control type="label">
        <posx>860</posx>
        <posy>0</posy>
        <width>960</width>
        <height>{{ vscale(64) }}</height>
        <font>font12</font>
        <align>left</align>
        <aligny>center</aligny>
        <textcolor>FF9C9C9C</textcolor>
        <label>$INFO[Window.Property(status)]</label>
    </control>

    <control type="list" id="101">
        <posx>70</posx>
        <posy>{{ vscale(84) }}</posy>
        <width>1780</width>
        <height>{{ vscale(700) }}</height>
        <onup>650</onup>
        <onleft>650</onleft>
        <scrolltime tween="quadratic" easing="out">200</scrolltime>
        <itemlayout height="{{ vscale(96) }}" width="1780">
            {% include "includes/arr_result_row.xml.tpl" %}
        </itemlayout>
        <focusedlayout height="{{ vscale(96) }}" width="1780">
            <control type="image">
                <posx>0</posx>
                <posy>0</posy>
                <width>1780</width>
                <height>{{ vscale(88) }}</height>
                <texture border="4">script.plex/white-square-rounded.png</texture>
                <colordiffuse>50FFFFFF</colordiffuse>
            </control>
            {% include "includes/arr_result_row.xml.tpl" %}
        </focusedlayout>
    </control>
</control>
{% endblock %}
