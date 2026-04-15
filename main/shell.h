#pragma once

#include <stddef.h>

void shell_start(void);
void shell_execute_command(const char *command, char *output, size_t output_size);
