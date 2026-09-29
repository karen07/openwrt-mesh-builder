import{readfile} from "fs";
import{cursor} from "uci";

let u = cursor();
let b = json(readfile("/etc/board.json"));

let generations = [ "EHT", "HE", "VHT", "HT" ];
let widths = [ 320, 160, 80, 40, 20 ];

u.foreach (
    "wireless", "wifi-device", function(r) {
        if (!r.path || !r.band)
            return;

        let band;

        if (r.band == "2g")
            band = "2G";
        else if (r.band == "5g")
            band = "5G";
        else if (r.band == "6g")
            band = "6G";
        else
            return;

        for (let name in b.wlan) {
            let w = b.wlan[name];

            if (w.path != r.path && !(type(w.path) == "array" && index(w.path, r.path) >= 0))
                continue;

            if (!w.info || !w.info.bands || !w.info.bands[band])
                return;

            let info = w.info.bands[band];
            let found = false;

            for (let generation in generations) {
                for (let width in widths) {
                    let mode = generation + width;

                    if (index(info.modes, mode) >= 0) {
                        printf("set wireless.%s.htmode=%s\n", r[".name"], mode);

                        found = true;
                        break;
                    }
                }

                if (found)
                    break;
            }

            if (info.default_channel)
                printf("set wireless.%s.channel=%d\n", r[".name"], info.default_channel);

            return;
        }
    });
