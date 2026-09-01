{% extends "default.xml.tpl" %}
{% block headers %}<defaultcontrol>101</defaultcontrol>{% endblock %}
{% block topleft_add %}
<control type="label">
    <width max="500">auto</width>
    <height>{{ vscale(40) }}</height>
    <font>font12</font>
    <align>left</align>
    <aligny>center</aligny>
    <textcolor>FFFFFFFF</textcolor>
    <label>[UPPERCASE]$INFO[Window.Property(heading)][/UPPERCASE]</label>
</control>
{% endblock %}
{% block content %}
<control type="group">
    <posx>0</posx>
    <posy>{{ vscale(135) }}</posy>

    <control type="label">
        <posx>70</posx>
        <posy>{{ vscale(10) }}</posy>
        <width>1260</width>
        <height>{{ vscale(48) }}</height>
        <font>font12</font>
        <align>left</align>
        <aligny>center</aligny>
        <textcolor>FFB4B4B4</textcolor>
        <label>$INFO[Window.Property(status)]</label>
    </control>

    <control type="grouplist" id="210">
        <posx>1380</posx>
        <posy>{{ vscale(4) }}</posy>
        <width>470</width>
        <height>{{ vscale(48) }}</height>
        <align>right</align>
        <itemgap>12</itemgap>
        <orientation>horizontal</orientation>
        <onup>200</onup>
        <ondown>101</ondown>
        <onleft>101</onleft>
        <onright>101</onright>
        <control type="button" id="205">
            <width max="300">auto</width>
            <height>{{ vscale(48) }}</height>
            <font>font12</font>
            <textcolor>FFEDEDED</textcolor>
            <focusedcolor>FF000000</focusedcolor>
            <align>center</align><aligny>center</aligny>
            <textoffsetx>22</textoffsetx>
            <texturefocus colordiffuse="FFE5A00D" border="10">script.plex/white-square-rounded.png</texturefocus>
            <texturenofocus colordiffuse="30FFFFFF" border="10">script.plex/white-square-rounded.png</texturenofocus>
            <label>$ADDON[script.plexmod 35083]</label>
        </control>
        <control type="button" id="203">
            <width max="160">auto</width>
            <height>{{ vscale(48) }}</height>
            <font>font12</font>
            <textcolor>FFEDEDED</textcolor>
            <focusedcolor>FF000000</focusedcolor>
            <align>center</align><aligny>center</aligny>
            <textoffsetx>22</textoffsetx>
            <texturefocus colordiffuse="FFE5A00D" border="10">script.plex/white-square-rounded.png</texturefocus>
            <texturenofocus colordiffuse="30FFFFFF" border="10">script.plex/white-square-rounded.png</texturenofocus>
            <label>$ADDON[script.plexmod 35064]</label>
        </control>
    </control>

    <control type="label">
        <visible>!String.IsEmpty(Window.Property(refreshing))</visible>
        <posx>1780</posx>
        <posy>{{ vscale(10) }}</posy>
        <width>100</width>
        <height>{{ vscale(40) }}</height>
        <font>font12</font>
        <align>right</align>
        <aligny>center</aligny>
        <textcolor>FFE5A00D</textcolor>
        <label>$ADDON[script.plexmod 35064]</label>
    </control>

    <control type="list" id="101">
        <visible>String.IsEmpty(Window.Property(no.content))</visible>
        <posx>70</posx>
        <posy>{{ vscale(64) }}</posy>
        <width>1780</width>
        <height>{{ vscale(820) }}</height>
        <onleft>200</onleft>
        <onright>101</onright>
        <onup>210</onup>
        <ondown>101</ondown>
        <scrolltime tween="quadratic" easing="out">300</scrolltime>
        <itemlayout height="{{ vscale(88) }}" width="1780">
            <control type="image">
                <posx>0</posx>
                <posy>0</posy>
                <width>1780</width>
                <height>{{ vscale(80) }}</height>
                <texture border="4">script.plex/white-square-rounded.png</texture>
                <colordiffuse>20FFFFFF</colordiffuse>
            </control>
            {% include "includes/download_row.xml.tpl" %}
        </itemlayout>
        <focusedlayout height="{{ vscale(88) }}" width="1780">
            <control type="image">
                <posx>0</posx>
                <posy>0</posy>
                <width>1780</width>
                <height>{{ vscale(80) }}</height>
                <texture border="4">script.plex/white-square-rounded.png</texture>
                <colordiffuse>50FFFFFF</colordiffuse>
            </control>
            {% include "includes/download_row.xml.tpl" %}
        </focusedlayout>
    </control>

    <control type="label">
        <visible>!String.IsEmpty(Window.Property(no.content))</visible>
        <posx>70</posx>
        <posy>{{ vscale(300) }}</posy>
        <width>1780</width>
        <height>{{ vscale(60) }}</height>
        <font>font13</font>
        <align>center</align>
        <aligny>center</aligny>
        <textcolor>FF9C9C9C</textcolor>
        <label>$INFO[Window.Property(status)]</label>
    </control>
</control>
{% endblock %}
