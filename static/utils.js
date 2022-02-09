if (!Array.prototype.last) {
    Array.prototype.last = function () {
        return this[this.length - 1];
    };
};

if (!Map.prototype.setne) {
    Map.prototype.setne = function (key, value) {
        if (!this.has(key)) {
            this.set(key, value);
        }
    }
}