module RefModule(input clk, input [7:0] d, input [1:0] sel, output [7:0] q);
  reg [7:0] stage1, stage2, stage3;
  reg [7:0] q_int;
  always @(posedge clk) begin
    stage1 <= d;
    stage2 <= stage1;
    stage3 <= stage2;
  end
  always @(*) begin
    case (sel)
      2'd0: q_int = d;
      2'd1: q_int = stage1;
      2'd2: q_int = stage2;
      2'd3: q_int = stage3;
    endcase
  end
  assign q = q_int;
endmodule
