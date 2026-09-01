            <control type="progress">
                <posx>0</posx>
                <posy>{{ vscale(70) }}</posy>
                <width>1780</width>
                <height>{{ vscale(8) }}</height>
                <info>ListItem.Property(percent)</info>
                <midtexture colordiffuse="FFE5A00D">script.plex/white-square.png</midtexture>
            </control>
            <control type="label">
                <posx>24</posx>
                <posy>{{ vscale(8) }}</posy>
                <width>1080</width>
                <height>{{ vscale(34) }}</height>
                <font>font13</font>
                <align>left</align>
                <aligny>center</aligny>
                <textcolor>FFEDEDED</textcolor>
                <label>$INFO[ListItem.Label]</label>
            </control>
            <control type="label">
                <posx>24</posx>
                <posy>{{ vscale(40) }}</posy>
                <width>1080</width>
                <height>{{ vscale(28) }}</height>
                <font>font10</font>
                <align>left</align>
                <aligny>center</aligny>
                <textcolor>FF9C9C9C</textcolor>
                <label>$INFO[ListItem.Label2]$INFO[ListItem.Property(message), · ,]</label>
            </control>
            <control type="label">
                <posx>1420</posx>
                <posy>{{ vscale(8) }}</posy>
                <width>160</width>
                <height>{{ vscale(34) }}</height>
                <font>font12</font>
                <align>right</align>
                <aligny>center</aligny>
                <textcolor>FFEDEDED</textcolor>
                <label>$INFO[ListItem.Property(percent.display)]</label>
            </control>
            <control type="label">
                <posx>1756</posx>
                <posy>{{ vscale(8) }}</posy>
                <width>340</width>
                <height>{{ vscale(34) }}</height>
                <font>font12</font>
                <align>right</align>
                <aligny>center</aligny>
                <textcolor>FFB4B4B4</textcolor>
                <label>$INFO[ListItem.Property(state)]$INFO[ListItem.Property(eta), · ,]</label>
            </control>
            <control type="label">
                <posx>1756</posx>
                <posy>{{ vscale(40) }}</posy>
                <width>340</width>
                <height>{{ vscale(28) }}</height>
                <font>font10</font>
                <align>right</align>
                <aligny>center</aligny>
                <textcolor>FF9C9C9C</textcolor>
                <label>$INFO[ListItem.Property(source)]$INFO[ListItem.Property(size), · ,]</label>
            </control>
