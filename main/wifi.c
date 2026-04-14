#include <string.h>
#include <stdio.h>
#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "wifi.h"

#define WIFI_SCAN_MAX_PRINT 20

static const char *auth_to_str(wifi_auth_mode_t auth) {
    switch (auth) {
        case WIFI_AUTH_OPEN: return "OPEN";
        case WIFI_AUTH_WEP: return "WEP";
        case WIFI_AUTH_WPA_PSK: return "WPA";
        case WIFI_AUTH_WPA2_PSK: return "WPA2";
        case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2";
        case WIFI_AUTH_WPA3_PSK: return "WPA3";
        case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3";
        default: return "UNKNOWN";
    }
}

void wifi_start_sta(const char *ssid, const char *password) {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t wifi_config = {0};
    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA_PSK;

    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    esp_wifi_start();
    esp_wifi_connect();
}

void wifi_reconnect(void) {
    esp_wifi_connect();
}

int wifi_is_connected(void) {
    wifi_ap_record_t ap_info;
    return esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK;
}

void wifi_scan_print(void) {
    wifi_scan_config_t scan_cfg = {0};
    if (esp_wifi_scan_start(&scan_cfg, true) != ESP_OK) {
        printf("scan failed\n");
        return;
    }

    uint16_t ap_count = 0;
    if (esp_wifi_scan_get_ap_num(&ap_count) != ESP_OK) {
        printf("scan count failed\n");
        return;
    }

    if (ap_count == 0) {
        printf("no networks found\n");
        return;
    }

    uint16_t show = ap_count > WIFI_SCAN_MAX_PRINT ? WIFI_SCAN_MAX_PRINT : ap_count;
    wifi_ap_record_t aps[WIFI_SCAN_MAX_PRINT];
    if (esp_wifi_scan_get_ap_records(&show, aps) != ESP_OK) {
        printf("scan read failed\n");
        return;
    }

    printf("found %u networks (show %u)\n", ap_count, show);
    for (uint16_t i = 0; i < show; i++) {
        const char *name = aps[i].ssid[0] ? (char *)aps[i].ssid : "<hidden>";
        printf("%2u) %s | RSSI %d | CH %u | %s\n",
               i + 1,
               name,
               aps[i].rssi,
               aps[i].primary,
               auth_to_str(aps[i].authmode));
    }
}
