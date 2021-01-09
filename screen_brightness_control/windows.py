import wmi, threading, pythoncom, ctypes, win32api
from ctypes import windll, byref, Structure, WinError, POINTER, WINFUNCTYPE
from ctypes.wintypes import BOOL, HMONITOR, HDC, RECT, LPARAM, DWORD, BYTE, WCHAR, HANDLE
from . import flatten_list, _monitor_brand_lookup, filter_monitors, Monitor, __cache__

def _wmi_init():
    '''internal function to create and return a wmi instance'''
    try:
        return __cache__.get('wmi_instance')
    except:
        #WMI calls don't work in new threads so we have to run this check
        if threading.current_thread() != threading.main_thread():
            pythoncom.CoInitialize()
        instance = wmi.WMI(namespace='wmi')
        __cache__.store('wmi_instance', instance)
        return instance

class WMI:
    '''collection of screen brightness related methods using the WMI API'''
    def get_display_info(display=None):
        '''
        Returns a dictionary of info about all detected monitors

        Args:
            display (str or int): [*Optional*] the monitor to return info about. Pass in the serial number, name, model, edid or index

        Returns:
            list: list of dictonaries
            dict: one dictionary if a monitor is specified
        
        Example:
            ```python
            import screen_brightness_control as sbc

            info = sbc.windows.WMI.get_display_info()
            for i in info:
                print('================')
                for key, value in i.items():
                    print(key, ':', value)

            # get information about the first WMI addressable monitor
            primary_info = sbc.windows.WMI.get_display_info(0)

            # get information about a monitor with a specific name
            benq_info = sbc.windows.WMI.get_display_info('BenQ GL2450H')
            ```
        '''
        try:
            info = __cache__.get('wmi_monitor_info')
        except:
            info = []
            a = 0
            try:
                wmi = _wmi_init()
                monitors = wmi.WmiMonitorBrightness()
                try:descriptors = {i.InstanceName:i.WmiGetMonitorRawEEdidV1Block(0) for i in wmi.WmiMonitorDescriptorMethods()}
                except:pass
                for m in monitors:
                    instance = m.InstanceName.split('\\')
                    serial = instance[-1]
                    model = instance[1]

                    man_id = model[:3]
                    try:man_id, manufacturer = _monitor_brand_lookup(model[:3])
                    except:manufacturer = None

                    try:
                        edid = ''.join([str(hex(i)).replace('0x','') for i in descriptors[m.InstanceName][0]])
                    except:
                        edid = None

                    tmp = {'name':f'{manufacturer} {model}', 'model':model, 'model_name': None, 'serial':serial, 'manufacturer': manufacturer, 'manufacturer_id': man_id , 'index': a, 'method': WMI, 'edid':edid}
                    info.append(tmp)
                    a+=1
            except:
                pass
            __cache__.store('wmi_monitor_info', info)
        if display!=None:
            indexes = [i['index'] for i in filter_monitors(display=display, haystack=info, method='wmi')]
            info = [info[i] for i in indexes]
        return info
    def get_display_names():
        '''
        Returns names of all displays that can be addressed by WMI

        Returns:
            list: list of strings
        
        Example:
            ```python
            import screen_brightness_control as sbc

            for name in sbc.windows.WMI.get_display_names():
                print(name)
            ```
        '''
        return [i['name'] for i in WMI.get_display_info()]
    def set_brightness(value, display = None, no_return = False):
        '''
        Sets the display brightness for Windows using WMI

        Args:
            value (int): The percentage to set the brightness to
            display (int or str): The index display you wish to set the brightness for OR the model of the display, as returned by self.get_display_names
            no_return (bool): if True, this function returns None, otherwise it returns the result of `WMI.get_brightness()`

        Returns:
            int: from 0 to 100 if only one display's brightness is requested
            list: list of integers if multiple displays are requested
            None: if `no_return` is set to `True`
        
        Raises:
            LookupError: if the given display cannot be found

        Example:
            ```python
            import screen_brightness_control as sbc

            # set brightness of WMI addressable monitors to 50%
            sbc.windows.WMI.set_brightness(50)

            # set the primary display brightness to 75%
            sbc.windows.WMI.set_brightness(75, display = 0)

            # set the brightness of a named monitor to 25%
            sbc.windows.WMI.set_brightness(25, display = 'BenQ GL2450H')
            ```
        '''
        brightness_method = _wmi_init().WmiMonitorBrightnessMethods()
        if display!=None:
            indexes = [i['index'] for i in filter_monitors(display=display, method='wmi')]
            brightness_method = [brightness_method[i] for i in indexes]
        for method in brightness_method:
            method.WmiSetBrightness(value,0)
        return WMI.get_brightness(display=display) if not no_return else None
    def get_brightness(display = None):
        '''
        Returns the current display brightness using the `wmi` API

        Args:
            display (int): The index display you wish to get the brightness of OR the model of that display

        Returns:
            int: from 0 to 100 if only one display's brightness is requested
            list: list of integers if multiple displays are requested
        
        Raises:
            LookupError: if the given display cannot be found
        
        Example:
            ```python
            import screen_brightness_control as sbc

            # get brightness of all WMI addressable monitors
            current_brightness = sbc.windows.WMI.get_brightness()
            if type(current_brightness) is int:
                print('There is only one detected display')
            else:
                print('There are', len(current_brightness), 'detected displays')

            # get the primary display brightness
            primary_brightness = sbc.windows.WMI.get_brightness(display = 0)

            # get the brightness of a named monitor
            benq_brightness = sbc.windows.WMI.get_brightness(display = 'BenQ GL2450H')
            ```
        '''
        brightness_method = _wmi_init().WmiMonitorBrightness()
        if display!=None:
            indexes = [i['index'] for i in filter_monitors(display=display, method='wmi')]
            brightness_method = [brightness_method[i] for i in indexes]
        values = [i.CurrentBrightness for i in brightness_method]
        return values[0] if len(values)==1 else values

class VCP:
    '''Collection of screen brightness related methods using the DDC/CI commands'''
    _MONITORENUMPROC = WINFUNCTYPE(BOOL, HMONITOR, HDC, POINTER(RECT), LPARAM)
    class _PHYSICAL_MONITOR(Structure):
        '''internal class, do not call'''
        _fields_ = [('handle', HANDLE),
                    ('description', WCHAR * 128)]

    def iter_physical_monitors():
        '''
        A generator to iterate through all physical monitors and then close them again afterwards, yielding their handles.
        It is not recommended to use this function unless you are familiar with `ctypes` and `windll`

        Raises:
            ctypes.WinError: upon failure to enumerate through the monitors

        Example:
            ```python
            import screen_brightness_control as sbc

            for monitor in sbc.windows.VCP.iter_physical_monitors():
                print(sbc.windows.VCP.get_monitor_caps(monitor))
            ```
        '''
        def callback(hmonitor, hdc, lprect, lparam):
            monitors.append(HMONITOR(hmonitor))
            return True

        monitors = []
        if not windll.user32.EnumDisplayMonitors(None, None, VCP._MONITORENUMPROC(callback), None):
            raise WinError('EnumDisplayMonitors failed')
        for monitor in monitors:
            # Get physical monitor count
            count = DWORD()
            if not windll.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(monitor, byref(count)):
                raise WinError()
            if count.value>0:
                # Get physical monitor handles
                physical_array = (VCP._PHYSICAL_MONITOR * count.value)()
                if not windll.dxva2.GetPhysicalMonitorsFromHMONITOR(monitor, count.value, physical_array):
                    raise WinError()
                for item in physical_array:
                    yield item.handle
                    windll.dxva2.DestroyPhysicalMonitor(item.handle)
    def filter_displays(display, *args):
        '''
        Deprecated. Redirects to top-level `filter_monitors` function.
        Searches through the information for all detected VCP displays and attempts to return the info matching the value given.
        Will attempt to match against index, name, model, edid and serial

        Args:
            args (tuple): [*Optional*] if `args` isn't empty the function searches through args[0]. Otherwise it searches through the return of `VCP.get_display_info()`
            display (str or int): what you are searching for. Can be serial number, name, model number, edid string or index of the display

        Raises:
            IndexError: if the display value is an int and an `IndexError` occurs when using it as a list index
            LookupError: if the display, as a str, does not have a match

        Returns:
            dict
        
        Example:
            ```python
            import screen_brightness_control as sbc

            search = 'GL2450H'
            match = sbc.windows.VCP.filter_displays(search)
            print(match)
            # EG output: {'name': 'BenQ GL2450H', 'model': 'GL2450H', ... }
            ```
        '''
        if len(args)==1:
            info = args[0]
        else:
            info = VCP.get_display_info()
        return filter_monitors(display = display, haystack = info, method='vcp')
    def get_display_info(display=None):
        '''
        Returns a dictionary of info about all detected monitors or a selection of monitors

        Args:
            display (int or str): [*Optional*] the monitor to return info about. Pass in the serial number, name, model, edid or index

        Returns:
            list: list of dicts if `args` is empty or there are multiple values passed in `args`
            dict: if one value was passed through `args` and it matched a known monitor
        
        Example:
            ```python
            import screen_brightness_control as sbc

            # get the information about all monitors
            vcp_info = sbc.windows.VCP.get_display_info()
            print(vcp_info)
            # EG output: [{'name': 'BenQ GL2450H', 'model': 'GL2450H', ... }, {'name': 'Dell U2211H', 'model': 'U2211H', ... }]

            # get information about a monitor with this specific model
            bnq_info = sbc.windows.VCP.get_display_info('GL2450H')
            # EG output: {'name': 'BenQ GL2450H', 'model': 'GL2450H', ... }
            ```
        '''
        try:
            info = __cache__.get('vcp_monitor_info')
        except:
            info = []
            try:
                monitors_sorted = [win32api.EnumDisplayDevices(win32api.GetMonitorInfo(i[0])['Device'], 0, 1).DeviceID.split('#')[2] for i in win32api.EnumDisplayMonitors()]
                wmi = _wmi_init()
                monitors = sorted(wmi.WmiMonitorID(), key=lambda x:monitors_sorted.index(x.InstanceName.replace('_0','',1).split('\\')[2]))

                try:descriptors = {i.InstanceName:i.WmiGetMonitorRawEEdidV1Block(0) for i in wmi.WmiMonitorDescriptorMethods()}
                except:pass
                a=0
                for monitor in monitors:
                    try:
                        serial = bytes(monitor.SerialNumberID).decode().replace('\x00', '')
                        manufacturer, model = bytes(monitor.UserFriendlyName).decode().replace('\x00', '').split(' ')
                        manufacturer = manufacturer.lower().capitalize()
                        try:man_id, manufacturer = _monitor_brand_lookup(manufacturer)
                        except:man_id = None
                        try:
                            edid = ''.join([str(hex(i)).replace('0x','') for i in descriptors[monitor.InstanceName][0]])
                        except:
                            edid = None

                        tmp = {'name':f'{manufacturer} {model}', 'model':model, 'model_name': None, 'serial':serial, 'manufacturer': manufacturer, 'manufacturer_id': man_id , 'index': a, 'method': VCP, 'edid': edid}
                        info.append(tmp)
                        a+=1
                    except:
                        pass
            except:
                pass
            __cache__.store('vcp_monitor_info', info)
        if display!=None:
            try:
                info = filter_monitors(display=display, haystack=info, method='vcp')
                return info[0] if len(info)==1 else info
            except:
                pass
        return info
    def get_monitor_caps(monitor):
        '''
        Fetches and returns the VCP capabilities string of a monitor.
        This function takes anywhere from 1-2 seconds to run

        Args:
            monitor: a monitor handle as returned by `VCP.iter_physical_monitors()`
        
        Returns:
            str: a string of the monitor's capabilities
        
        Examples:
            ```python
            import screen_brightness_control as sbc

            for monitor in sbc.windows.VCP.iter_physical_monitors():
                print(sbc.windows.VCP.get_monitor_caps(monitor))
            # EG output: '(prot(monitor)type(LCD)model(GL2450HM)cmds(01 02 03 07 0C F3)vcp(02 04 05 08 0B 0C 10 12 14(04 05 08 0B) 16 18 1A 52 60(01 03 11)62 8D(01 02)AC AE B2 B6 C0 C6 C8 C9 CA(01 02) CC(01 02 03 04 05 06 09 0A 0B 0D 0E 12 14 1A 1E 1F 20)D6(01 05) DF)mswhql(1)mccs_ver(2.1)asset_eep(32)mpu_ver(1.02))'
            ```
        '''
        caps_string_length = DWORD()
        if not windll.dxva2.GetCapabilitiesStringLength(monitor,ctypes.byref(caps_string_length)):
            return
        caps_string = (ctypes.c_char * caps_string_length.value)()
        if not windll.dxva2.CapabilitiesRequestAndCapabilitiesReply(monitor, caps_string, caps_string_length):
            return
        return caps_string.value.decode('ASCII')
    def get_display_names():
        '''
        Return the names of each detected monitor
        
        Returns:
            list: list of strings
        
        Example:
            ```python
            import screen_brightness_control as sbc

            names = sbc.windows.VCP.get_display_names()
            print(names)
            # EG output: ['BenQ GL2450H', 'Dell U2211H']
            ```
        '''
        return [i['name'] for i in VCP.get_display_info()]
    def get_brightness(display=None):
        '''
        Retrieve the brightness of all connected displays using the `ctypes.windll` API

        Args:
            display (int or str): the specific display you wish to query. Is passed to `filter_monitors` to match to a display
        
        Returns:
            list: list of ints from 0 to 100 if multiple displays are detected and the `display` kwarg is not set
            int: from 0 to 100 if there is only one display detected or the `display` kwarg is set
        
        Examples:
            ```python
            import screen_brightness_control as sbc

            # Get the brightness for all detected displays
            current_brightness = sbc.windows.VCP.get_brightness()
            if type(current_brightness) is int:
                print('There is only one detected display')
            else:
                print('There are', len(current_brightness), 'detected displays')
            
            # Get the brightness for the primary display
            primary_brightness = sbc.windows.VCP.get_brightness(display = 0)

            # Get the brightness for a secondary display
            secondary_brightness = sbc.windows.VCP.get_brightness(display = 1)

            # Get the brightness for a display with the model 'GL2450H'
            benq_brightness = sbc.windows.VCP.get_brightness(display = 'GL2450H')
            ```
        '''
        if display!=None:
            all_monitors = VCP.get_display_info()
            monitors = filter_monitors(display = display, haystack=all_monitors)
            indexes = [i['index'] for i in monitors]

        count = 0
        values = []
        for m in VCP.iter_physical_monitors():
            try:
                v = __cache__.get('vcp_'+all_monitors[count]['edid']+'_brightness')
            except:
                cur_out = DWORD()
                if windll.dxva2.GetVCPFeatureAndVCPFeatureReply(HANDLE(m), BYTE(0x10), None, byref(cur_out), None):
                    v = cur_out.value
                else:
                    v = None
                del(cur_out)
            if v!=None and (display==None or (count in indexes)):
                try:
                    __cache__.store('vcp_'+all_monitors[count]['edid']+'_brightness', v, expires=0.5)
                except IndexError:pass
                values.append(v)
            count+=1

        if values==[]:
            return None
        return values[0] if len(values)==1 else values
    def set_brightness(value, display=None, no_return=False):
        '''
        Sets the brightness for all connected displays using the `ctypes.windll` API

        Args:
            display (int or str): the specific display you wish to query. Is passed to `filter_monitors` to match to a display
            no_return (bool): if set to `True` this function will return `None`
        
        Returns:
            The result of `VCP.get_brightness()` (with the same `display` kwarg) if `no_return` is not set
        
        Examples:
            ```python
            import screen_brightness_control as sbc

            # Set the brightness for all detected displays to 50%
            sbc.windows.VCP.set_brightness(50)
            
            # Set the brightness for the primary display to 75%
            sbc.windows.VCP.set_brightness(75, display = 0)

            # Set the brightness for a secondary display to 25%
            sbc.windows.VCP.set_brightness(25, display = 1)

            # Set the brightness for a display with the model 'GL2450H' to 100%
            sbc.windows.VCP.set_brightness(100, display = 'GL2450H')
            ```
        '''
        if display!=None:
            displays = filter_monitors(display = display, method='vcp')
            displays = [i['index'] for i in displays]
        loops = 0
        for m in VCP.iter_physical_monitors():
            if display==None or (loops in displays):
                windll.dxva2.SetVCPFeature(HANDLE(m), BYTE(0x10), DWORD(value))
            loops+=1
        return VCP.get_brightness(display=display) if not no_return else None


def list_monitors_info(method=None):
    '''
    Lists detailed information about all detected monitors

    Args:
        method (str): the method the monitor can be addressed by. Can be 'wmi' or 'vcp'

    Returns:
        list: list of dictionaries upon success, empty list upon failure

    Example:
        ```python
        import screen_brightness_control as sbc

        monitors = sbc.windows.list_monitors_info()
        for info in monitors:
            print('=======================')
            print('Name:', info['name']) # the manufacturer name plus the model
            print('Model:', info['model']) # the general model of the display
            print('Serial:', info['serial']) # a unique string assigned by Windows to this display
            print('Manufacturer:', info['manufacturer']) # the name of the brand of the monitor
            print('Manufacturer ID:', info['manufacturer_id']) # the 3 letter code corresponding to the brand name, EG: BNQ -> BenQ  
            print('Index:', info['index']) # the index of that display FOR THE SPECIFIC METHOD THE DISPLAY USES
            print('Method:', info['method']) # the method this monitor can be addressed by
            print('EDID:', info['edid']) # the EDID string of the monitor
        ```
    '''
    try:
        return __cache__.get('windows_monitors_info', method=method)
    except:
        methods = [WMI,VCP]
        if method!=None:
            methods = [i for i in methods if i.__name__.lower() == method.lower()]
            if methods==[]:
                raise ValueError('method kwarg must be \'wmi\' or \'vcp\'')

        info = []
        edids = []
        for m in methods:
            #to make sure each display (with unique edid) is only reported once
            for i in m.get_display_info():
                if i['edid'] not in edids:
                    edids.append(i['edid'])
                    info.append(i)
        __cache__.store('windows_monitors_info', info, method=method)
        return info

def list_monitors(method=None):
    '''
    Returns a list of all addressable monitor names

    Args:
        method (str): the method the monitor can be addressed by. Can be 'wmi' or 'vcp'

    Returns:
        list: list of strings

    Example:
        ```python
        import screen_brightness_control as sbc

        monitors = sbc.windows.list_monitors()
        # EG output: ['BenQ GL2450H', 'Dell U2211H']
        ```
    '''
    return [i['name'] for i in list_monitors_info(method=method)]

def __set_and_get_brightness(*args, display=None, method=None, meta_method='get', **kwargs):
    '''internal function, do not call.
    either sets the brightness or gets it. Exists because set_brightness and get_brightness only have a couple differences'''
    errors = []
    try: # filter known list of monitors according to kwargs
        monitors = filter_monitors(display = display, method = method)
    except Exception as e:
        errors.append(['',type(e).__name__, e])
    else:
        output = []
        for m in monitors: # add the output of each brightness method to the output list
            try:
                output.append(
                    getattr(m['method'], meta_method+'_brightness')(*args, display = m['serial'], **kwargs)
                )
            except Exception as e:
                output.append(None)
                errors.append([f"{m['name']} ({m['serial']})", type(e).__name__, e])

        if output!=[] and not all(i==None for i in output): # flatten and return any output
            output = flatten_list(output)
            return output[0] if len(output)==1 else output

    #if function hasn't already returned it has failed
    msg='\n'
    for e in errors:
        msg+=f'\t{e[0]} -> {e[1]}: {e[2]}\n'
    if msg=='\n':
        msg+='\tno valid output was received from brightness methods'
    raise Exception(msg)

def set_brightness(value, display=None, method = None, **kwargs):
    '''
    Sets the brightness of any connected monitors

    Args:
        value (int): Sets the brightness to this value as a percentage
        display (int or str): the specific display you wish to adjust. can be index, model, name or serial of the display
        method (str): the method to use ('wmi' or 'vcp')
        kwargs (dict): passed directly to the chosen brightness method

    Returns:
        Whatever the called methods return (See `WMI.set_brightness` and `VCP.set_brightness` for details).
        Typically it will list, int (0 to 100) or None
    
    Raises:
        LookupError: if the chosen display (with method if applicable) is not found
        ValueError: if the chosen method is invalid
        TypeError: if the value given for `display` is not int or str
        Exception: if the brightness could not be set by any method

    Example:
        ```python
        import screen_brightness_control as sbc

        # set the current brightness to 50%
        sbc.windows.set_brightness(50)

        # set the brightness of the primary display to 75%
        sbc.windows.set_brightness(75, display = 0)

        # set the brightness of any displays using VCP to 25%
        sbc.windows.set_brightness(25, method = 'vcp')

        # set the brightness of displays with the model name 'BenQ GL2450H' (see `list_monitors` and `list_monitors_info`) to 100%
        sbc.windows.set_brightness(100, display = 'BenQ GL2450H')
        ```
    '''
    # this function is called because set_brightness and get_brightness only differed by 1 line of code
    # so I made another internal function to reduce the filesize
    return __set_and_get_brightness(value, display=display, method=method, meta_method='set', **kwargs)

def get_brightness(display = None, method = None, **kwargs):
    '''
    Returns the brightness of any connected monitors

    Args:
        display (int or str): the specific display you wish to adjust. can be index, model, name or serial of the display
        method (str): the method to use ('wmi' or 'vcp')
        kwargs (dict): passed directly to chosen brightness method

    Returns:
        int: from 0 to 100 if only one display is detected or the `display` kwarg is set
        list: list of integers if multiple displays are detected and the `display` kwarg isn't set (invalid monitors return `None`)
    
    Raises:
        LookupError: if the chosen display (with method if applicable) is not found
        ValueError: if the chosen method is invalid
        TypeError: if the value given for `display` is not int or str
        Exception: if the brightness could not be obtained by any method

    Example:
        ```python
        import screen_brightness_control as sbc

        # get the current brightness
        current_brightness = sbc.windows.get_brightness()
        if type(current_brightness) is int:
            print('There is only one detected display')
        else:
            print('There are', len(current_brightness), 'detected displays')

        # get the brightness of the primary display
        primary_brightness = sbc.windows.get_brightness(display = 0)

        # get the brightness of any displays using VCP
        vcp_brightness = sbc.windows.get_brightness(method = 'vcp')

        # get the brightness of displays with the model name 'BenQ GL2450H'
        benq_brightness = sbc.windows.get_brightness(display = 'BenQ GL2450H')
        ```
    '''
    # this function is called because set_brightness and get_brightness only differed by 1 line of code
    # so I made another internal function to reduce the filesize
    return __set_and_get_brightness(display=display, method=method, meta_method='get', **kwargs)
