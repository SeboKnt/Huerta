#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdarg.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_err.h"
#include "wifi.h"
#include "shell.h"
#include "relay.h"
#include "cloud_client.h"

static void trim_line(char *line, int *len) {
    if (!line || !len) {
        return;
    }

    while (*len > 0 && (line[*len - 1] == ' ' || line[*len - 1] == '\t')) {
        line[*len - 1] = '\0';
        (*len)--;
    }
}

static void print_device_serial(void) {
    uint8_t mac[6] = {0};
    if (esp_efuse_mac_get_default(mac) != ESP_OK) {
        printf("serial read failed\n");
        return;
    }

    printf("serial: %02X%02X%02X%02X%02X%02X\n",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void print_ram_status(void) {
    size_t free_bytes = heap_caps_get_free_size(MALLOC_CAP_8BIT);
    size_t total_bytes = heap_caps_get_total_size(MALLOC_CAP_8BIT);
    size_t used_bytes = 0;

    if (total_bytes > free_bytes) {
        used_bytes = total_bytes - free_bytes;
    }

    printf(
        "ram: %u/%u KB used\n",
        (unsigned int)(used_bytes / 1024U),
        (unsigned int)(total_bytes / 1024U)
    );
}

static void append_output(char *output, size_t output_size, const char *fmt, ...) {
    if (!output || output_size == 0 || !fmt) {
        return;
    }

    size_t used = strlen(output);
    if (used >= output_size - 1) {
        return;
    }

    va_list args;
    va_start(args, fmt);
    vsnprintf(output + used, output_size - used, fmt, args);
    va_end(args);
}

void shell_execute_command(const char *command, char *output, size_t output_size) {
    if (!output || output_size == 0) {
        return;
    }
    output[0] = '\0';

    if (!command || command[0] == '\0') {
        append_output(output, output_size, "empty command");
        return;
    }

    if (strcmp(command, "help") == 0) {
        append_output(output, output_size, "help status reconnect scan serial identify relay relay t");
    } else if (strcmp(command, "status") == 0) {
        int cpu_load_pct = cloud_get_last_cpu_load_pct();
        append_output(
            output,
            output_size,
            "wifi=%s cpu=%d%%",
            wifi_is_connected() ? "connected" : "not connected",
            cpu_load_pct >= 0 ? cpu_load_pct : 0
        );
    } else if (strcmp(command, "reconnect") == 0) {
        wifi_reconnect();
        append_output(output, output_size, "reconnect requested");
    } else if (strcmp(command, "scan") == 0) {
        wifi_scan_print();
        append_output(output, output_size, "scan finished (see serial output for list)");
    } else if (strcmp(command, "serial") == 0) {
        uint8_t mac[6] = {0};
        if (esp_efuse_mac_get_default(mac) == ESP_OK) {
            append_output(
                output,
                output_size,
                "serial=%02X%02X%02X%02X%02X%02X",
                mac[0],
                mac[1],
                mac[2],
                mac[3],
                mac[4],
                mac[5]
            );
        } else {
            append_output(output, output_size, "serial read failed");
        }
    } else if (strcmp(command, "identify") == 0) {
        bool was_active = cloud_is_identify_active();
        esp_err_t err = cloud_toggle_identify_state();
        if (err == ESP_OK) {
            append_output(
                output,
                output_size,
                "%s",
                was_active ? "identify stop requested" : "identify sequence started"
            );
        } else {
            append_output(output, output_size, "identify failed: %s", esp_err_to_name(err));
        }
    } else if (strcmp(command, "relay") == 0) {
        esp_err_t err = relay_init();
        if (err == ESP_OK) {
            append_output(output, output_size, "relay=%s", relay_is_on_state() ? "on" : "off");
        } else {
            append_output(output, output_size, "relay init failed: %s", esp_err_to_name(err));
        }
    } else if (strcmp(command, "relay t") == 0) {
        esp_err_t err = relay_toggle();
        if (err == ESP_OK) {
            append_output(output, output_size, "relay toggled: %s", relay_is_on_state() ? "on" : "off");
        } else {
            append_output(output, output_size, "relay toggle failed: %s", esp_err_to_name(err));
        }
    } else {
        append_output(output, output_size, "unknown command: %s", command);
    }
}

static void shell_task(void *arg) {
    (void)arg;
    char line[64];
    int pos = 0;
    int last_was_cr = 0;

    printf("shell ready: help | status | reconnect | scan | serial | identify | relay\n");
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

            trim_line(line, &pos);

            if (strcmp(line, "status") == 0) {
                printf("wifi: %s\n", wifi_is_connected() ? "connected" : "not connected");
                print_ram_status();
                int cpu_load_pct = cloud_get_last_cpu_load_pct();
                if (cpu_load_pct >= 0) {
                    printf("cpu load (last heartbeat): %d%%\n", cpu_load_pct);
                } else {
                    printf("cpu load (last heartbeat): n/a\n");
                }
            } else if (strcmp(line, "serial") == 0) {
                print_device_serial();
            } else if (line[0] != '\0') {
                char output[256];
                shell_execute_command(line, output, sizeof(output));
                if (output[0] != '\0') {
                    printf("%s\n", output);
                }
                if (strcmp(line, "help") == 0) {
                    printf("help      - show commands\n");
                    printf("status    - wifi, ram and cpu info\n");
                    printf("reconnect - call esp_wifi_connect()\n");
                    printf("scan      - list nearby wifi networks\n");
                    printf("serial    - show device serial number\n");
                    printf("identify  - run identify for 60s\n");
                    printf("relay     - show GPIO23 state\n");
                    printf("relay t   - toggle GPIO23\n");
                }
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
