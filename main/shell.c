#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_mac.h"
#include "wifi.h"
#include "shell.h"

static void print_device_serial(void) {
    uint8_t mac[6] = {0};
    if (esp_efuse_mac_get_default(mac) != ESP_OK) {
        printf("serial read failed\n");
        return;
    }

    printf("serial: %02X%02X%02X%02X%02X%02X\n",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void shell_task(void *arg) {
    (void)arg;
    char line[64];
    int pos = 0;
    int last_was_cr = 0;

    printf("shell ready: help | status | reconnect | scan | serial\n");
    printf("> ");
    fflush(stdout);
    while (1) {
        int ch = getchar();
        if (ch < 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        if (ch == '\r' || ch == '\n') {
            if (ch == '\n' && last_was_cr) {
                last_was_cr = 0;
                continue;
            }
            last_was_cr = (ch == '\r');
            line[pos] = '\0';
            printf("\n");

            if (strcmp(line, "help") == 0) {
                printf("help      - show commands\n");
                printf("status    - wifi connected?\n");
                printf("reconnect - call esp_wifi_connect()\n");
                printf("scan      - list nearby wifi networks\n");
                printf("serial    - show device serial number\n");
            } else if (strcmp(line, "status") == 0) {
                printf("wifi: %s\n", wifi_is_connected() ? "connected" : "not connected");
            } else if (strcmp(line, "reconnect") == 0) {
                wifi_reconnect();
                printf("reconnect requested\n");
            } else if (strcmp(line, "scan") == 0) {
                wifi_scan_print();
            } else if (strcmp(line, "serial") == 0) {
                print_device_serial();
            } else if (line[0] != '\0') {
                printf("unknown command: %s\n", line);
            }

            pos = 0;
            printf("> ");
            fflush(stdout);
            continue;
        }
        last_was_cr = 0;

        if (ch == 0x08 || ch == 0x7F) {
            if (pos > 0) {
                pos--;
                printf("\b \b");
                fflush(stdout);
            }
            continue;
        }

        if (pos < (int)sizeof(line) - 1) {
            line[pos++] = (char)ch;
            putchar(ch);
            fflush(stdout);
        }
    }
}

void shell_start(void) {
    xTaskCreate(shell_task, "shell", 4096, NULL, 5, NULL);
}
