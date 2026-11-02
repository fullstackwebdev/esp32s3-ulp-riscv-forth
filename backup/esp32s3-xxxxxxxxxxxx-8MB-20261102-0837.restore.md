# Restore esp32s3-xxxxxxxxxxxx-8MB-20261102-0837

    esptool.py -p <port> -b 921600 write_flash 0 backup/esp32s3-xxxxxxxxxxxx-8MB-20261102-0837.bin
    ( cd backup && sha256sum -c esp32s3-xxxxxxxxxxxx-8MB-20261102-0837.bin.sha256 )   # before writing, and again on a re-read

Written by tools/backup_board.sh: three reads of the whole flash, all agreeing (sha256 `1ac78214737679c9f3b0f4aa36a307bae6b01198dece3d3cb1d9684aa7ea0884`),
which is the only reason this file can be trusted later.
