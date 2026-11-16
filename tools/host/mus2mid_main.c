/* Host tool: MUS -> MIDI (format 1), using the port's own mus2mid.c.
 * usage: mus2mid in.mus out.mid */
#include <stdio.h>
#include <stdlib.h>
#include "mus2mid.h"

int main(int argc, char** argv)
{
    if(argc != 3)
        return 2;

    FILE* f = fopen(argv[1], "rb");
    if(!f)
        return 1;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    rewind(f);
    char* mus = malloc(len);
    fread(mus, 1, len, f);
    fclose(f);

    char* mid = NULL;
    size_t midlen = 0;
    int err = mus2mid(mus, len, &mid, &midlen, 64);
    if(err)
    {
        fprintf(stderr, "mus2mid: error %d\n", err);
        return 1;
    }

    f = fopen(argv[2], "wb");
    fwrite(mid, 1, midlen, f);
    fclose(f);
    return 0;
}
