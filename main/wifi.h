#pragma once

void wifi_start_sta(const char *ssid, const char *password);
void wifi_reconnect(void);
int wifi_is_connected(void);
void wifi_scan_print(void);
