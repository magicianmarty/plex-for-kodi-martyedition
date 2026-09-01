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
        <width>1500</width>
        <height>{{ vscale(40) }}</height>
        <font>font12</font>
        <align>left</align>
        <aligny>center</aligny>
        <textcolor>FFB4B4B4</textcolor>
        <label>$INFO[Window.Property(status)]</label>
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
        <posy>{{ vscale(60) }}</posy>
        <width>1780</width>
        <height>{{ vscale(830) }}</height>
        <onleft>200</onleft>
        <onright>101</onright>
        <onup>101</onup>
        <ondown>101</ondown>
        <scrolltime tween="quadratic" easing="out">300</scrolltime>
        <itemlayout height="{{ vscale(92) }}" width="1780">
            <control type="image">
                <posx>0</posx>
                <posy>0</posy>
                <width>1780</width>
                <height>{{ vscale(84) }}</height>
                <texture border="4">script.plex/white-square-rounded.png</texture>
                <colordiffuse>20FFFFFF</colordiffuse>
            </control>
            {% include "includes/download_row.xml.tpl" %}
        </itemlayout>
        <focusedlayout height="{{ vscale(92) }}" width="1780">
            <control type="image">
                <posx>0</posx>
                <posy>0</posy>
                <width>1780</width>
                <height>{{ vscale(84) }}</height>
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
